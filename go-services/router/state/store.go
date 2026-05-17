package state

import (
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
)

// StepResult represents a single step execution result.
type StepResult struct {
	Step   int    `json:"step"`
	Agent  string `json:"agent"`
	Status string `json:"status"`
	Output string `json:"output"`
	Error  string `json:"error,omitempty"`
}

// TaskState holds the full state of a routed task.
type TaskState struct {
	TaskID      string        `json:"task_id"`
	UserInput   string        `json:"user_input"`
	Intent      string        `json:"intent"`
	Status      string        `json:"status"`
	Steps       []StepResult  `json:"steps"`
	FinalOutput string        `json:"final_output,omitempty"`
	CreatedAt   int64         `json:"created_at"`
	UpdatedAt   int64         `json:"updated_at"`
	Trace       []TraceEvent  `json:"-"`
}

// TraceEvent is a timestamped event for audit/logging.
type TraceEvent struct {
	Event     string `json:"event"`
	Detail    string `json:"detail"`
	Timestamp int64  `json:"timestamp"`
}

// Store is a thread-safe in-memory state graph for router tasks.
type Store struct {
	mu       sync.RWMutex
	states   map[string]*TaskState
	events   []map[string]any
	watchers []chan map[string]any
}

// NewStore creates an empty state store.
func NewStore() *Store {
	return &Store{
		states:   make(map[string]*TaskState),
		events:   make([]map[string]any, 0),
		watchers: make([]chan map[string]any, 0),
	}
}

// Create initializes a new task state.
func (s *Store) Create(userInput, intent string) *TaskState {
	now := time.Now().UnixMilli()
	state := &TaskState{
		TaskID:    uuid.New().String()[:12],
		UserInput: userInput,
		Intent:    intent,
		Status:    "planned",
		Steps:     make([]StepResult, 0),
		CreatedAt: now,
		UpdatedAt: now,
		Trace: []TraceEvent{
			{Event: "state_created", Detail: fmt.Sprintf("intent=%s", intent), Timestamp: now},
		},
	}

	s.mu.Lock()
	s.states[state.TaskID] = state
	s.emit(map[string]any{
		"event":   "state_created",
		"task_id": state.TaskID,
		"intent":  intent,
	})
	s.mu.Unlock()
	return state
}

// Get retrieves a task state by ID.
func (s *Store) Get(id string) (*TaskState, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	state, ok := s.states[id]
	return state, ok
}

// AddStep appends a step result and updates the state.
func (s *Store) AddStep(id string, result StepResult) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	state, ok := s.states[id]
	if !ok {
		return false
	}
	now := time.Now().UnixMilli()
	state.Steps = append(state.Steps, result)
	state.UpdatedAt = now
	state.Trace = append(state.Trace, TraceEvent{
		Event:  "step_completed",
		Detail: fmt.Sprintf("step=%d agent=%s status=%s", result.Step, result.Agent, result.Status),
		Timestamp: now,
	})
	s.emit(map[string]any{
		"event":   "step_completed",
		"task_id": id,
		"step":    result.Step,
		"agent":   result.Agent,
		"status":  result.Status,
	})
	return true
}

// Complete marks a task as completed with final output.
func (s *Store) Complete(id, output string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	state, ok := s.states[id]
	if !ok {
		return false
	}
	now := time.Now().UnixMilli()
	state.Status = "completed"
	state.FinalOutput = output
	state.UpdatedAt = now
	state.Trace = append(state.Trace, TraceEvent{
		Event:     "task_completed",
		Timestamp: now,
	})
	s.emit(map[string]any{
		"event":   "task_completed",
		"task_id": id,
	})
	return true
}

// Fail marks a task as failed.
func (s *Store) Fail(id, errMsg string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	state, ok := s.states[id]
	if !ok {
		return false
	}
	now := time.Now().UnixMilli()
	state.Status = "failed"
	state.UpdatedAt = now
	state.Trace = append(state.Trace, TraceEvent{
		Event:     "task_failed",
		Detail:    errMsg,
		Timestamp: now,
	})
	s.emit(map[string]any{
		"event":   "task_failed",
		"task_id": id,
		"error":   errMsg,
	})
	return true
}

// List returns task states optionally filtered by status.
func (s *Store) List(status string, limit int) []*TaskState {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]*TaskState, 0, len(s.states))
	for _, state := range s.states {
		if status == "" || state.Status == status {
			result = append(result, state)
		}
	}
	return result
}

// Delete removes a task state by ID.
func (s *Store) Delete(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.states[id]
	if ok {
		delete(s.states, id)
		s.emit(map[string]any{
			"event":   "state_deleted",
			"task_id": id,
		})
	}
	return ok
}

// Trace returns the event trace for a task.
func (s *Store) Trace(id string) []TraceEvent {
	s.mu.RLock()
	defer s.mu.RUnlock()
	state, ok := s.states[id]
	if !ok {
		return nil
	}
	return state.Trace
}

// Subscribe returns a channel that receives all state change events.
func (s *Store) Subscribe() <-chan map[string]any {
	ch := make(chan map[string]any, 64)
	s.mu.Lock()
	s.watchers = append(s.watchers, ch)
	s.mu.Unlock()
	return ch
}

// Unsubscribe removes a watcher channel.
func (s *Store) Unsubscribe(ch <-chan map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, w := range s.watchers {
		if w == ch {
			s.watchers = append(s.watchers[:i], s.watchers[i+1:]...)
			close(w)
			return
		}
	}
}

func (s *Store) emit(event map[string]any) {
	for _, w := range s.watchers {
		select {
		case w <- event:
		default:
		}
	}
}
