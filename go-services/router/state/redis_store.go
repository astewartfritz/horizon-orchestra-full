package state

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisStore wraps Store with Redis persistence for horizontal scaling.
// Falls back to in-memory store when Redis is unavailable.
type RedisStore struct {
	*Store
	client    *redis.Client
	namespace string
	ttl       time.Duration
	connected bool
	ctx       context.Context
}

// NewRedisStore creates a Redis-backed state store.
// Falls back to plain Store if Redis connection fails.
func NewRedisStore(redisURL string) *RedisStore {
	rs := &RedisStore{
		Store:     NewStore(),
		namespace: "orchestra:state:",
		ttl:       24 * time.Hour,
		ctx:       context.Background(),
	}

	if redisURL == "" {
		redisURL = os.Getenv("REDIS_URL")
	}
	if redisURL == "" {
		redisURL = "redis://localhost:6379/0"
	}

	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Printf("RedisStore: invalid URL %s, using in-memory: %v", redisURL, err)
		return rs
	}

	rs.client = redis.NewClient(opts)

	// Test connection in background — don't block startup
	go func() {
		ctx, cancel := context.WithTimeout(rs.ctx, 3*time.Second)
		defer cancel()
		if err := rs.client.Ping(ctx).Err(); err != nil {
			log.Printf("RedisStore: connection failed, using in-memory: %v", err)
			rs.connected = false
			return
		}
		rs.connected = true
		log.Printf("RedisStore: connected to %s", redisURL)
	}()

	return rs
}

func (rs *RedisStore) stateKey(id string) string {
	return rs.namespace + id
}

func (rs *RedisStore) traceKey(id string) string {
	return rs.namespace + "trace:" + id
}

// Create persists the new state to Redis and the in-memory store.
func (rs *RedisStore) Create(userInput, intent string) *TaskState {
	state := rs.Store.Create(userInput, intent)
	rs.persist(state)
	return state
}

// Get retrieves from in-memory first, falls back to Redis.
func (rs *RedisStore) Get(id string) (*TaskState, bool) {
	s, ok := rs.Store.Get(id)
	if ok {
		return s, true
	}
	return rs.fetch(id)
}

// AddStep persists the step to both stores.
func (rs *RedisStore) AddStep(id string, result StepResult) bool {
	ok := rs.Store.AddStep(id, result)
	if ok {
		rs.persistByID(id)
	}
	return ok
}

// Complete persists the completed state.
func (rs *RedisStore) Complete(id, output string) bool {
	ok := rs.Store.Complete(id, output)
	if ok {
		rs.persistByID(id)
	}
	return ok
}

// Fail persists the failed state.
func (rs *RedisStore) Fail(id, errMsg string) bool {
	ok := rs.Store.Fail(id, errMsg)
	if ok {
		rs.persistByID(id)
	}
	return ok
}

// Delete removes from both stores.
func (rs *RedisStore) Delete(id string) bool {
	ok := rs.Store.Delete(id)
	if rs.connected && rs.client != nil {
		rs.client.Del(rs.ctx, rs.stateKey(id), rs.traceKey(id))
	}
	return ok
}

// ── Redis persistence ──

func (rs *RedisStore) persist(state *TaskState) {
	if !rs.connected || rs.client == nil {
		return
	}
	data, err := json.Marshal(state)
	if err != nil {
		log.Printf("RedisStore: marshal error: %v", err)
		return
	}
	if err := rs.client.Set(rs.ctx, rs.stateKey(state.TaskID), data, rs.ttl).Err(); err != nil {
		log.Printf("RedisStore: set error: %v", err)
		rs.connected = false
	}
}

func (rs *RedisStore) persistByID(id string) {
	s, ok := rs.Store.Get(id)
	if ok {
		rs.persist(s)
	}
}

func (rs *RedisStore) fetch(id string) (*TaskState, bool) {
	if !rs.connected || rs.client == nil {
		return nil, false
	}
	data, err := rs.client.Get(rs.ctx, rs.stateKey(id)).Bytes()
	if err != nil {
		return nil, false
	}
	var state TaskState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, false
	}
	// Restore into in-memory store for fast subsequent access
	rs.Store.mu.Lock()
	rs.Store.states[id] = &state
	rs.Store.mu.Unlock()
	return &state, true
}
