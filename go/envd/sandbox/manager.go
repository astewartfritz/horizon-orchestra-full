// Package sandbox implements the core sandbox lifecycle management for envd.
// It supports both Firecracker microVM isolation and fallback process-level isolation.
package sandbox

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/google/uuid"
	log "github.com/sirupsen/logrus"
)

// SandboxState represents the current lifecycle state of a sandbox.
type SandboxState string

const (
	StateCreating  SandboxState = "creating"
	StateRunning   SandboxState = "running"
	StatePaused    SandboxState = "paused"
	StateStopping  SandboxState = "stopping"
	StateStopped   SandboxState = "stopped"
	StateError     SandboxState = "error"
)

// SandboxConfig specifies the desired configuration for a new sandbox.
type SandboxConfig struct {
	Name          string            `json:"name"`
	VCPUs         int               `json:"vcpus"`
	MemoryMB      int               `json:"memory_mb"`
	DiskSizeMB    int               `json:"disk_size_mb"`
	NetworkEnabled bool             `json:"network_enabled"`
	Environment   map[string]string `json:"environment"`
	WorkDir       string            `json:"work_dir"`
	TimeoutSec    int               `json:"timeout_sec"`
	Labels        map[string]string `json:"labels"`
}

// ExecResult holds the output from a command execution inside a sandbox.
type ExecResult struct {
	ExitCode int    `json:"exit_code"`
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
	Duration time.Duration `json:"duration"`
	OOMKilled bool  `json:"oom_killed"`
	TimedOut  bool  `json:"timed_out"`
}

// SandboxInfo provides summary information about a running sandbox.
type SandboxInfo struct {
	ID         string            `json:"id"`
	Name       string            `json:"name"`
	State      SandboxState      `json:"state"`
	CreatedAt  time.Time         `json:"created_at"`
	VCPUs      int               `json:"vcpus"`
	MemoryMB   int               `json:"memory_mb"`
	PID        int               `json:"pid"`
	Labels     map[string]string `json:"labels"`
	Isolation  string            `json:"isolation"` // "firecracker" or "process"
	HealthOK   bool              `json:"health_ok"`
}

// ManagerConfig configures the SandboxManager.
type ManagerConfig struct {
	MaxSandboxes      int
	WorkspaceRoot     string
	EnableFirecracker bool
	FirecrackerBin    string
	KernelImage       string
	RootfsImage       string
	OverlayDir        string
	CgroupRoot        string
}

// sandboxEntry is the internal tracking record for a live sandbox.
type sandboxEntry struct {
	info      SandboxInfo
	config    SandboxConfig
	cancel    context.CancelFunc
	overlay   string
	cgroupDir string
	fc        *FirecrackerVM // nil when using process isolation
}

// Manager manages the full lifecycle of sandboxes.
type Manager struct {
	mu         sync.RWMutex
	sandboxes  map[string]*sandboxEntry
	config     ManagerConfig
	fcEnabled  bool
}

// NewManager creates a new sandbox manager and validates its configuration.
func NewManager(cfg ManagerConfig) (*Manager, error) {
	if cfg.MaxSandboxes <= 0 {
		cfg.MaxSandboxes = 16
	}
	if cfg.WorkspaceRoot == "" {
		cfg.WorkspaceRoot = "/home/user/workspace"
	}
	if cfg.OverlayDir == "" {
		cfg.OverlayDir = "/var/lib/envd/overlays"
	}
	if cfg.CgroupRoot == "" {
		cfg.CgroupRoot = "/sys/fs/cgroup/envd"
	}

	// Check if Firecracker is available.
	fcEnabled := cfg.EnableFirecracker
	if fcEnabled {
		if _, err := os.Stat(cfg.FirecrackerBin); os.IsNotExist(err) {
			log.Warn("firecracker binary not found, falling back to process isolation")
			fcEnabled = false
		}
	}

	// Ensure overlay directory exists.
	if err := os.MkdirAll(cfg.OverlayDir, 0o755); err != nil {
		return nil, fmt.Errorf("create overlay dir: %w", err)
	}

	mgr := &Manager{
		sandboxes: make(map[string]*sandboxEntry),
		config:    cfg,
		fcEnabled: fcEnabled,
	}

	log.WithFields(log.Fields{
		"max_sandboxes": cfg.MaxSandboxes,
		"firecracker":   fcEnabled,
		"overlay_dir":   cfg.OverlayDir,
	}).Info("sandbox manager initialized")

	return mgr, nil
}

// CreateSandbox provisions a new sandbox and returns its unique ID.
func (m *Manager) CreateSandbox(ctx context.Context, cfg SandboxConfig) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if len(m.sandboxes) >= m.config.MaxSandboxes {
		return "", fmt.Errorf("maximum sandbox count (%d) reached", m.config.MaxSandboxes)
	}

	id := uuid.New().String()
	sandboxCtx, cancel := context.WithCancel(ctx)

	// Apply defaults.
	if cfg.VCPUs <= 0 {
		cfg.VCPUs = 2
	}
	if cfg.MemoryMB <= 0 {
		cfg.MemoryMB = 512
	}
	if cfg.TimeoutSec <= 0 {
		cfg.TimeoutSec = 300
	}

	// Setup filesystem overlay.
	overlayPath, err := m.setupOverlay(id)
	if err != nil {
		cancel()
		return "", fmt.Errorf("setup overlay: %w", err)
	}

	// Setup cgroup for resource limits.
	cgroupDir, err := m.setupCgroup(id, cfg)
	if err != nil {
		cancel()
		m.cleanupOverlay(overlayPath)
		return "", fmt.Errorf("setup cgroup: %w", err)
	}

	entry := &sandboxEntry{
		info: SandboxInfo{
			ID:        id,
			Name:      cfg.Name,
			State:     StateCreating,
			CreatedAt: time.Now(),
			VCPUs:     cfg.VCPUs,
			MemoryMB:  cfg.MemoryMB,
			Labels:    cfg.Labels,
			HealthOK:  true,
		},
		config:    cfg,
		cancel:    cancel,
		overlay:   overlayPath,
		cgroupDir: cgroupDir,
	}

	// Start the sandbox with either Firecracker or process isolation.
	if m.fcEnabled {
		fcVM, err := StartFirecrackerVM(sandboxCtx, FirecrackerConfig{
			ID:             id,
			BinaryPath:     m.config.FirecrackerBin,
			KernelImage:    m.config.KernelImage,
			RootfsImage:    m.config.RootfsImage,
			VCPUs:          cfg.VCPUs,
			MemoryMB:       cfg.MemoryMB,
			NetworkEnabled: cfg.NetworkEnabled,
			OverlayPath:    overlayPath,
		})
		if err != nil {
			cancel()
			m.cleanupOverlay(overlayPath)
			m.cleanupCgroup(cgroupDir)
			return "", fmt.Errorf("start firecracker VM: %w", err)
		}
		entry.fc = fcVM
		entry.info.PID = fcVM.PID()
		entry.info.Isolation = "firecracker"
	} else {
		entry.info.Isolation = "process"
	}

	entry.info.State = StateRunning
	m.sandboxes[id] = entry

	log.WithFields(log.Fields{
		"sandbox_id": id,
		"name":       cfg.Name,
		"isolation":  entry.info.Isolation,
		"vcpus":      cfg.VCPUs,
		"memory_mb":  cfg.MemoryMB,
	}).Info("sandbox created")

	return id, nil
}

// DestroySandbox terminates and cleans up a sandbox by ID.
func (m *Manager) DestroySandbox(id string) error {
	m.mu.Lock()
	entry, ok := m.sandboxes[id]
	if !ok {
		m.mu.Unlock()
		return fmt.Errorf("sandbox %s not found", id)
	}
	entry.info.State = StateStopping
	m.mu.Unlock()

	// Cancel the sandbox context.
	entry.cancel()

	// Shutdown Firecracker VM if running.
	if entry.fc != nil {
		if err := entry.fc.Shutdown(5 * time.Second); err != nil {
			log.Warnf("firecracker shutdown error for %s: %v", id, err)
		}
	}

	// Cleanup resources.
	m.cleanupOverlay(entry.overlay)
	m.cleanupCgroup(entry.cgroupDir)

	m.mu.Lock()
	delete(m.sandboxes, id)
	m.mu.Unlock()

	log.WithField("sandbox_id", id).Info("sandbox destroyed")
	return nil
}

// ExecInSandbox runs a command inside the specified sandbox.
func (m *Manager) ExecInSandbox(ctx context.Context, id string, command []string) (*ExecResult, error) {
	m.mu.RLock()
	entry, ok := m.sandboxes[id]
	m.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("sandbox %s not found", id)
	}
	if entry.info.State != StateRunning {
		return nil, fmt.Errorf("sandbox %s is not running (state: %s)", id, entry.info.State)
	}

	timeout := time.Duration(entry.config.TimeoutSec) * time.Second
	execCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	start := time.Now()
	var result ExecResult

	if entry.fc != nil {
		// Execute via Firecracker VM serial/vsock.
		res, err := entry.fc.Exec(execCtx, command)
		if err != nil {
			return nil, fmt.Errorf("exec in firecracker: %w", err)
		}
		result = *res
	} else {
		// Process-isolation fallback: run in namespace with cgroup.
		result = m.execProcess(execCtx, entry, command)
	}

	result.Duration = time.Since(start)

	// Check if context was cancelled due to timeout.
	if execCtx.Err() == context.DeadlineExceeded {
		result.TimedOut = true
	}

	return &result, nil
}

// execProcess runs a command using process isolation with cgroup limits.
func (m *Manager) execProcess(ctx context.Context, entry *sandboxEntry, command []string) ExecResult {
	if len(command) == 0 {
		return ExecResult{ExitCode: 1, Stderr: "empty command"}
	}

	cmd := exec.CommandContext(ctx, command[0], command[1:]...)
	cmd.Dir = entry.overlay

	// Set environment.
	for k, v := range entry.config.Environment {
		cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", k, v))
	}
	cmd.Env = append(cmd.Env, "HOME="+entry.overlay)
	cmd.Env = append(cmd.Env, "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")

	// Set process isolation attributes.
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Cloneflags: syscall.CLONE_NEWUTS | syscall.CLONE_NEWPID | syscall.CLONE_NEWIPC,
		Pdeathsig:  syscall.SIGKILL,
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			exitCode = 1
		}
	}

	return ExecResult{
		ExitCode: exitCode,
		Stdout:   stdout.String(),
		Stderr:   stderr.String(),
	}
}

// ListSandboxes returns info about all active sandboxes.
func (m *Manager) ListSandboxes() []SandboxInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()

	infos := make([]SandboxInfo, 0, len(m.sandboxes))
	for _, entry := range m.sandboxes {
		infos = append(infos, entry.info)
	}
	return infos
}

// GetSandboxInfo returns info for a single sandbox.
func (m *Manager) GetSandboxInfo(id string) (*SandboxInfo, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	entry, ok := m.sandboxes[id]
	if !ok {
		return nil, fmt.Errorf("sandbox %s not found", id)
	}
	info := entry.info
	return &info, nil
}

// DestroyAll terminates all running sandboxes. Used during shutdown.
func (m *Manager) DestroyAll() {
	m.mu.RLock()
	ids := make([]string, 0, len(m.sandboxes))
	for id := range m.sandboxes {
		ids = append(ids, id)
	}
	m.mu.RUnlock()

	for _, id := range ids {
		if err := m.DestroySandbox(id); err != nil {
			log.Warnf("error destroying sandbox %s during shutdown: %v", id, err)
		}
	}
}

// Shutdown performs a clean shutdown of the manager.
func (m *Manager) Shutdown() {
	log.Info("sandbox manager shutting down")
	m.DestroyAll()
}

// RunHealthMonitor periodically checks the health of all sandboxes.
func (m *Manager) RunHealthMonitor(ctx context.Context, interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			m.checkAllHealth()
		}
	}
}

// checkAllHealth pings each sandbox and updates its health status.
func (m *Manager) checkAllHealth() {
	m.mu.Lock()
	defer m.mu.Unlock()

	for id, entry := range m.sandboxes {
		if entry.info.State != StateRunning {
			continue
		}

		healthy := true
		if entry.fc != nil {
			healthy = entry.fc.IsHealthy()
		}

		if !healthy && entry.info.HealthOK {
			log.WithField("sandbox_id", id).Warn("sandbox health check failed")
		}
		entry.info.HealthOK = healthy
	}
}

// HealthStatus returns an aggregated health status of the manager.
func (m *Manager) HealthStatus() map[string]interface{} {
	m.mu.RLock()
	defer m.mu.RUnlock()

	total := len(m.sandboxes)
	healthy := 0
	for _, entry := range m.sandboxes {
		if entry.info.HealthOK {
			healthy++
		}
	}

	return map[string]interface{}{
		"status":           "ok",
		"total_sandboxes":  total,
		"healthy_sandboxes": healthy,
		"max_sandboxes":    m.config.MaxSandboxes,
		"firecracker":      m.fcEnabled,
	}
}

// setupOverlay creates an overlay filesystem for a sandbox.
func (m *Manager) setupOverlay(id string) (string, error) {
	overlayPath := filepath.Join(m.config.OverlayDir, id)
	dirs := []string{
		filepath.Join(overlayPath, "upper"),
		filepath.Join(overlayPath, "work"),
		filepath.Join(overlayPath, "merged"),
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return "", fmt.Errorf("mkdir %s: %w", d, err)
		}
	}

	log.WithField("sandbox_id", id).Debug("overlay filesystem created")
	return overlayPath, nil
}

// cleanupOverlay removes the overlay filesystem for a sandbox.
func (m *Manager) cleanupOverlay(overlayPath string) {
	if overlayPath == "" {
		return
	}
	if err := os.RemoveAll(overlayPath); err != nil {
		log.Warnf("failed to cleanup overlay %s: %v", overlayPath, err)
	}
}

// setupCgroup creates a cgroup for sandbox resource limits.
func (m *Manager) setupCgroup(id string, cfg SandboxConfig) (string, error) {
	cgroupDir := filepath.Join(m.config.CgroupRoot, id)
	if err := os.MkdirAll(cgroupDir, 0o755); err != nil {
		// Non-fatal: cgroups may not be available in all environments.
		log.Warnf("cgroup setup failed for %s (non-fatal): %v", id, err)
		return "", nil
	}

	// Set memory limit.
	memLimitBytes := int64(cfg.MemoryMB) * 1024 * 1024
	memFile := filepath.Join(cgroupDir, "memory.max")
	_ = os.WriteFile(memFile, []byte(fmt.Sprintf("%d", memLimitBytes)), 0o644)

	// Set CPU limit (as a percentage of a single CPU * 100000).
	cpuQuota := cfg.VCPUs * 100000
	cpuFile := filepath.Join(cgroupDir, "cpu.max")
	_ = os.WriteFile(cpuFile, []byte(fmt.Sprintf("%d 100000", cpuQuota)), 0o644)

	log.WithFields(log.Fields{
		"sandbox_id": id,
		"memory_mb":  cfg.MemoryMB,
		"vcpus":      cfg.VCPUs,
	}).Debug("cgroup configured")

	return cgroupDir, nil
}

// cleanupCgroup removes the cgroup directory for a sandbox.
func (m *Manager) cleanupCgroup(cgroupDir string) {
	if cgroupDir == "" {
		return
	}
	if err := os.Remove(cgroupDir); err != nil {
		log.Warnf("failed to cleanup cgroup %s: %v", cgroupDir, err)
	}
}
