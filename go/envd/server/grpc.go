// Package server implements the gRPC and HTTP servers for the envd sandbox daemon.
package server

import (
	"context"
	"fmt"
	"time"

	log "github.com/sirupsen/logrus"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/astewartfritz/horizon-orchestra/go/envd/sandbox"
)

// SandboxServiceServer implements the gRPC SandboxService.
type SandboxServiceServer struct {
	manager *sandbox.Manager
}

// RegisterSandboxService registers the sandbox gRPC service on the given server.
func RegisterSandboxService(s *grpc.Server, mgr *sandbox.Manager) {
	svc := &SandboxServiceServer{manager: mgr}
	// In production, this would call the generated RegisterSandboxServiceServer
	// from the proto-generated code. Here we register manually for clarity.
	registerSandboxServiceServer(s, svc)
}

// registerSandboxServiceServer is a placeholder for protoc-generated registration.
// Replace with the actual generated function after running protoc.
func registerSandboxServiceServer(s *grpc.Server, svc *SandboxServiceServer) {
	// proto-gen: pb.RegisterSandboxServiceServer(s, svc)
	_ = s
	_ = svc
	log.Info("sandbox gRPC service registered (proto stub)")
}

// --- Request / Response types (mirrors proto definitions) ---

// CreateSandboxRequest is the gRPC request for creating a sandbox.
type CreateSandboxRequest struct {
	Name           string            `json:"name"`
	Vcpus          int32             `json:"vcpus"`
	MemoryMb       int32             `json:"memory_mb"`
	DiskSizeMb     int32             `json:"disk_size_mb"`
	NetworkEnabled bool              `json:"network_enabled"`
	Environment    map[string]string `json:"environment"`
	WorkDir        string            `json:"work_dir"`
	TimeoutSec     int32             `json:"timeout_sec"`
	Labels         map[string]string `json:"labels"`
}

// CreateSandboxResponse is the gRPC response for creating a sandbox.
type CreateSandboxResponse struct {
	SandboxID string `json:"sandbox_id"`
	Status    string `json:"status"`
}

// DestroySandboxRequest is the gRPC request for destroying a sandbox.
type DestroySandboxRequest struct {
	SandboxID string `json:"sandbox_id"`
	Force     bool   `json:"force"`
}

// DestroySandboxResponse is the gRPC response for destroying a sandbox.
type DestroySandboxResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

// ExecRequest is the gRPC request for executing a command in a sandbox.
type ExecRequest struct {
	SandboxID string   `json:"sandbox_id"`
	Command   []string `json:"command"`
	Stdin     []byte   `json:"stdin"`
	Tty       bool     `json:"tty"`
}

// ExecResponse is the gRPC response for command execution.
type ExecResponse struct {
	ExitCode  int32  `json:"exit_code"`
	Stdout    []byte `json:"stdout"`
	Stderr    []byte `json:"stderr"`
	DurationMs int64 `json:"duration_ms"`
	OomKilled bool   `json:"oom_killed"`
	TimedOut  bool   `json:"timed_out"`
}

// ListSandboxesRequest is the gRPC request for listing sandboxes.
type ListSandboxesRequest struct {
	LabelSelector map[string]string `json:"label_selector"`
}

// SandboxInfoProto is the protobuf representation of sandbox info.
type SandboxInfoProto struct {
	SandboxID  string            `json:"sandbox_id"`
	Name       string            `json:"name"`
	State      string            `json:"state"`
	CreatedAt  int64             `json:"created_at"`
	Vcpus      int32             `json:"vcpus"`
	MemoryMb   int32             `json:"memory_mb"`
	Pid        int32             `json:"pid"`
	Labels     map[string]string `json:"labels"`
	Isolation  string            `json:"isolation"`
	HealthOk   bool              `json:"health_ok"`
}

// ListSandboxesResponse is the gRPC response for listing sandboxes.
type ListSandboxesResponse struct {
	Sandboxes []SandboxInfoProto `json:"sandboxes"`
}

// HealthCheckRequest is the gRPC health check request.
type HealthCheckRequest struct{}

// HealthCheckResponse is the gRPC health check response.
type HealthCheckResponse struct {
	Healthy         bool   `json:"healthy"`
	TotalSandboxes  int32  `json:"total_sandboxes"`
	HealthySandboxes int32 `json:"healthy_sandboxes"`
	MaxSandboxes    int32  `json:"max_sandboxes"`
	UptimeSeconds   int64  `json:"uptime_seconds"`
}

var startTime = time.Now()

// Create handles the CreateSandbox RPC.
func (s *SandboxServiceServer) Create(ctx context.Context, req *CreateSandboxRequest) (*CreateSandboxResponse, error) {
	log.WithField("name", req.Name).Info("gRPC Create sandbox")

	cfg := sandbox.SandboxConfig{
		Name:           req.Name,
		VCPUs:          int(req.Vcpus),
		MemoryMB:       int(req.MemoryMb),
		DiskSizeMB:     int(req.DiskSizeMb),
		NetworkEnabled: req.NetworkEnabled,
		Environment:    req.Environment,
		WorkDir:        req.WorkDir,
		TimeoutSec:     int(req.TimeoutSec),
		Labels:         req.Labels,
	}

	id, err := s.manager.CreateSandbox(ctx, cfg)
	if err != nil {
		log.WithError(err).Error("failed to create sandbox")
		return nil, status.Errorf(codes.Internal, "create sandbox: %v", err)
	}

	return &CreateSandboxResponse{
		SandboxID: id,
		Status:    "running",
	}, nil
}

// Destroy handles the DestroySandbox RPC.
func (s *SandboxServiceServer) Destroy(ctx context.Context, req *DestroySandboxRequest) (*DestroySandboxResponse, error) {
	log.WithField("sandbox_id", req.SandboxID).Info("gRPC Destroy sandbox")

	if req.SandboxID == "" {
		return nil, status.Error(codes.InvalidArgument, "sandbox_id is required")
	}

	if err := s.manager.DestroySandbox(req.SandboxID); err != nil {
		return nil, status.Errorf(codes.NotFound, "destroy sandbox: %v", err)
	}

	return &DestroySandboxResponse{
		Success: true,
		Message: fmt.Sprintf("sandbox %s destroyed", req.SandboxID),
	}, nil
}

// Exec handles the Exec RPC. In production, this would be a server-streaming RPC
// for real-time output. Here we implement it as a unary call.
func (s *SandboxServiceServer) Exec(ctx context.Context, req *ExecRequest) (*ExecResponse, error) {
	log.WithFields(log.Fields{
		"sandbox_id": req.SandboxID,
		"command":    req.Command,
	}).Info("gRPC Exec")

	if req.SandboxID == "" {
		return nil, status.Error(codes.InvalidArgument, "sandbox_id is required")
	}
	if len(req.Command) == 0 {
		return nil, status.Error(codes.InvalidArgument, "command is required")
	}

	result, err := s.manager.ExecInSandbox(ctx, req.SandboxID, req.Command)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "exec: %v", err)
	}

	return &ExecResponse{
		ExitCode:   int32(result.ExitCode),
		Stdout:     []byte(result.Stdout),
		Stderr:     []byte(result.Stderr),
		DurationMs: result.Duration.Milliseconds(),
		OomKilled:  result.OOMKilled,
		TimedOut:   result.TimedOut,
	}, nil
}

// List handles the ListSandboxes RPC.
func (s *SandboxServiceServer) List(ctx context.Context, req *ListSandboxesRequest) (*ListSandboxesResponse, error) {
	log.Info("gRPC List sandboxes")

	infos := s.manager.ListSandboxes()
	protoInfos := make([]SandboxInfoProto, 0, len(infos))

	for _, info := range infos {
		// Apply label selector filter if provided.
		if len(req.LabelSelector) > 0 && !matchLabels(info.Labels, req.LabelSelector) {
			continue
		}

		protoInfos = append(protoInfos, SandboxInfoProto{
			SandboxID: info.ID,
			Name:      info.Name,
			State:     string(info.State),
			CreatedAt: info.CreatedAt.Unix(),
			Vcpus:     int32(info.VCPUs),
			MemoryMb:  int32(info.MemoryMB),
			Pid:       int32(info.PID),
			Labels:    info.Labels,
			Isolation: info.Isolation,
			HealthOk:  info.HealthOK,
		})
	}

	return &ListSandboxesResponse{Sandboxes: protoInfos}, nil
}

// HealthCheck handles the HealthCheck RPC.
func (s *SandboxServiceServer) HealthCheck(ctx context.Context, req *HealthCheckRequest) (*HealthCheckResponse, error) {
	hs := s.manager.HealthStatus()

	totalSandboxes, _ := hs["total_sandboxes"].(int)
	healthySandboxes, _ := hs["healthy_sandboxes"].(int)
	maxSandboxes, _ := hs["max_sandboxes"].(int)

	return &HealthCheckResponse{
		Healthy:          true,
		TotalSandboxes:   int32(totalSandboxes),
		HealthySandboxes: int32(healthySandboxes),
		MaxSandboxes:     int32(maxSandboxes),
		UptimeSeconds:    int64(time.Since(startTime).Seconds()),
	}, nil
}

// matchLabels returns true if all selector labels are present in the target labels.
func matchLabels(target, selector map[string]string) bool {
	for k, v := range selector {
		if target[k] != v {
			return false
		}
	}
	return true
}
