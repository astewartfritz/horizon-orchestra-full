package sandbox

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"
)

// FirecrackerConfig holds the configuration for launching a Firecracker microVM.
type FirecrackerConfig struct {
	ID             string
	BinaryPath     string
	KernelImage    string
	RootfsImage    string
	VCPUs          int
	MemoryMB       int
	NetworkEnabled bool
	OverlayPath    string
}

// FirecrackerVM represents a running Firecracker microVM instance.
type FirecrackerVM struct {
	mu         sync.Mutex
	id         string
	cmd        *exec.Cmd
	socketPath string
	pid        int
	running    bool
	httpClient *http.Client
}

// fcMachineConfig is the Firecracker API machine configuration payload.
type fcMachineConfig struct {
	VCPUCount  int  `json:"vcpu_count"`
	MemSizeMiB int  `json:"mem_size_mib"`
	SMT        bool `json:"smt"`
}

// fcBootSource is the Firecracker API boot source payload.
type fcBootSource struct {
	KernelImagePath string `json:"kernel_image_path"`
	BootArgs        string `json:"boot_args"`
}

// fcDrive is the Firecracker API drive configuration.
type fcDrive struct {
	DriveID      string `json:"drive_id"`
	PathOnHost   string `json:"path_on_host"`
	IsRootDevice bool   `json:"is_root_device"`
	IsReadOnly   bool   `json:"is_read_only"`
}

// fcNetworkInterface is the Firecracker API network interface config.
type fcNetworkInterface struct {
	IfaceID     string `json:"iface_id"`
	GuestMAC    string `json:"guest_mac,omitempty"`
	HostDevName string `json:"host_dev_name"`
}

// fcAction is a Firecracker API action request (e.g., InstanceStart).
type fcAction struct {
	ActionType string `json:"action_type"`
}

// StartFirecrackerVM launches a new Firecracker microVM and returns a handle to it.
// Target boot time: <125ms.
func StartFirecrackerVM(ctx context.Context, cfg FirecrackerConfig) (*FirecrackerVM, error) {
	socketPath := filepath.Join(os.TempDir(), fmt.Sprintf("fc-%s.sock", cfg.ID))

	// Remove stale socket if present.
	_ = os.Remove(socketPath)

	// Start the Firecracker process.
	cmd := exec.CommandContext(ctx, cfg.BinaryPath,
		"--api-sock", socketPath,
		"--id", cfg.ID,
		"--log-path", filepath.Join(os.TempDir(), fmt.Sprintf("fc-%s.log", cfg.ID)),
		"--level", "Warning",
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	bootStart := time.Now()

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start firecracker process: %w", err)
	}

	vm := &FirecrackerVM{
		id:         cfg.ID,
		cmd:        cmd,
		socketPath: socketPath,
		pid:        cmd.Process.Pid,
		running:    true,
		httpClient: &http.Client{
			Transport: &http.Transport{
				DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
					return net.DialTimeout("unix", socketPath, 2*time.Second)
				},
			},
			Timeout: 5 * time.Second,
		},
	}

	// Wait for the API socket to become available.
	if err := vm.waitForSocket(3 * time.Second); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("wait for firecracker socket: %w", err)
	}

	// Configure the machine.
	if err := vm.configureMachine(cfg); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("configure machine: %w", err)
	}

	// Configure boot source.
	if err := vm.configureBootSource(cfg); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("configure boot source: %w", err)
	}

	// Attach root drive.
	if err := vm.attachRootDrive(cfg); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("attach root drive: %w", err)
	}

	// Configure networking if enabled.
	if cfg.NetworkEnabled {
		if err := vm.configureNetwork(cfg); err != nil {
			log.Warnf("network setup failed for VM %s: %v", cfg.ID, err)
		}
	}

	// Start the instance.
	if err := vm.startInstance(); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("start instance: %w", err)
	}

	bootDuration := time.Since(bootStart)
	log.WithFields(log.Fields{
		"vm_id":         cfg.ID,
		"boot_time_ms":  bootDuration.Milliseconds(),
		"vcpus":         cfg.VCPUs,
		"memory_mb":     cfg.MemoryMB,
	}).Info("firecracker VM booted")

	if bootDuration > 125*time.Millisecond {
		log.Warnf("VM %s boot time (%dms) exceeded 125ms target", cfg.ID, bootDuration.Milliseconds())
	}

	// Monitor the process in background.
	go vm.monitor()

	return vm, nil
}

// waitForSocket polls until the API socket is available or timeout.
func (vm *FirecrackerVM) waitForSocket(timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(vm.socketPath); err == nil {
			// Try to connect.
			conn, err := net.DialTimeout("unix", vm.socketPath, 100*time.Millisecond)
			if err == nil {
				conn.Close()
				return nil
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	return fmt.Errorf("socket %s not ready after %v", vm.socketPath, timeout)
}

// apiPut sends a PUT request to the Firecracker API.
func (vm *FirecrackerVM) apiPut(path string, body interface{}) error {
	data, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequest(http.MethodPut, "http://localhost"+path, strings.NewReader(string(data)))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := vm.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("api request to %s: %w", path, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		return fmt.Errorf("api %s returned status %d", path, resp.StatusCode)
	}
	return nil
}

// configureMachine sets vCPU count and memory.
func (vm *FirecrackerVM) configureMachine(cfg FirecrackerConfig) error {
	return vm.apiPut("/machine-config", fcMachineConfig{
		VCPUCount:  cfg.VCPUs,
		MemSizeMiB: cfg.MemoryMB,
		SMT:        false,
	})
}

// configureBootSource sets the kernel image and boot args.
func (vm *FirecrackerVM) configureBootSource(cfg FirecrackerConfig) error {
	return vm.apiPut("/boot-source", fcBootSource{
		KernelImagePath: cfg.KernelImage,
		BootArgs:        "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/overlay-init",
	})
}

// attachRootDrive attaches the rootfs block device.
func (vm *FirecrackerVM) attachRootDrive(cfg FirecrackerConfig) error {
	return vm.apiPut("/drives/rootfs", fcDrive{
		DriveID:      "rootfs",
		PathOnHost:   cfg.RootfsImage,
		IsRootDevice: true,
		IsReadOnly:   false,
	})
}

// configureNetwork sets up a tap network interface.
func (vm *FirecrackerVM) configureNetwork(cfg FirecrackerConfig) error {
	tapName := fmt.Sprintf("tap-%s", cfg.ID[:8])
	return vm.apiPut("/network-interfaces/eth0", fcNetworkInterface{
		IfaceID:     "eth0",
		HostDevName: tapName,
	})
}

// startInstance sends the InstanceStart action.
func (vm *FirecrackerVM) startInstance() error {
	return vm.apiPut("/actions", fcAction{ActionType: "InstanceStart"})
}

// PID returns the Firecracker process PID.
func (vm *FirecrackerVM) PID() int {
	return vm.pid
}

// IsHealthy checks if the VM process is still running.
func (vm *FirecrackerVM) IsHealthy() bool {
	vm.mu.Lock()
	defer vm.mu.Unlock()
	return vm.running
}

// Exec executes a command inside the Firecracker VM via the serial console or vsock.
func (vm *FirecrackerVM) Exec(ctx context.Context, command []string) (*ExecResult, error) {
	vm.mu.Lock()
	if !vm.running {
		vm.mu.Unlock()
		return nil, fmt.Errorf("VM %s is not running", vm.id)
	}
	vm.mu.Unlock()

	// In a production implementation, this would communicate via vsock (AF_VSOCK)
	// to an agent running inside the VM. For now, we simulate with the API.
	cmdStr := strings.Join(command, " ")
	log.WithFields(log.Fields{
		"vm_id":   vm.id,
		"command": cmdStr,
	}).Debug("executing command in VM")

	// Placeholder: real implementation would use vsock guest agent.
	return &ExecResult{
		ExitCode: 0,
		Stdout:   fmt.Sprintf("[firecracker:%s] would execute: %s", vm.id, cmdStr),
		Stderr:   "",
	}, nil
}

// Shutdown gracefully stops the Firecracker VM.
func (vm *FirecrackerVM) Shutdown(timeout time.Duration) error {
	vm.mu.Lock()
	defer vm.mu.Unlock()

	if !vm.running {
		return nil
	}

	// Send SendCtrlAltDel action for graceful shutdown.
	_ = vm.apiPut("/actions", fcAction{ActionType: "SendCtrlAltDel"})

	// Wait for process to exit.
	done := make(chan error, 1)
	go func() {
		done <- vm.cmd.Wait()
	}()

	select {
	case <-done:
		log.Infof("firecracker VM %s shut down gracefully", vm.id)
	case <-time.After(timeout):
		log.Warnf("firecracker VM %s did not shut down in %v, killing", vm.id, timeout)
		_ = vm.cmd.Process.Kill()
	}

	vm.running = false

	// Cleanup socket.
	_ = os.Remove(vm.socketPath)

	return nil
}

// monitor watches the Firecracker process and marks it as not running on exit.
func (vm *FirecrackerVM) monitor() {
	_ = vm.cmd.Wait()

	vm.mu.Lock()
	vm.running = false
	vm.mu.Unlock()

	log.WithField("vm_id", vm.id).Info("firecracker VM process exited")
	_ = os.Remove(vm.socketPath)
}
