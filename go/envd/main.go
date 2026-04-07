// Package main is the entry point for the Horizon Orchestra sandbox daemon (envd).
// It starts a gRPC server for sandbox management and an HTTP health server.
package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	log "github.com/sirupsen/logrus"
	"google.golang.org/grpc"

	"github.com/astewartfritz/horizon-orchestra/go/envd/sandbox"
	"github.com/astewartfritz/horizon-orchestra/go/envd/server"
)

const (
	defaultGRPCAddr   = ":50051"
	defaultHealthAddr = ":8081"
	shutdownTimeout   = 15 * time.Second
)

// Config holds the daemon configuration loaded from environment variables.
type Config struct {
	GRPCAddr       string
	HealthAddr     string
	WorkspaceRoot  string
	MaxSandboxes   int
	LogLevel       string
	EnableFirecracker bool
	FirecrackerBin string
	KernelImage    string
	RootfsImage    string
	OverlayDir     string
	CgroupRoot     string
}

// LoadConfig reads configuration from environment variables with sensible defaults.
func LoadConfig() *Config {
	cfg := &Config{
		GRPCAddr:       envOrDefault("ENVD_GRPC_ADDR", defaultGRPCAddr),
		HealthAddr:     envOrDefault("ENVD_HEALTH_ADDR", defaultHealthAddr),
		WorkspaceRoot:  envOrDefault("ENVD_WORKSPACE_ROOT", "/home/user/workspace"),
		MaxSandboxes:   envOrDefaultInt("ENVD_MAX_SANDBOXES", 16),
		LogLevel:       envOrDefault("ENVD_LOG_LEVEL", "info"),
		EnableFirecracker: envOrDefault("ENVD_ENABLE_FIRECRACKER", "false") == "true",
		FirecrackerBin: envOrDefault("ENVD_FIRECRACKER_BIN", "/usr/local/bin/firecracker"),
		KernelImage:    envOrDefault("ENVD_KERNEL_IMAGE", "/var/lib/envd/vmlinux"),
		RootfsImage:    envOrDefault("ENVD_ROOTFS_IMAGE", "/var/lib/envd/rootfs.ext4"),
		OverlayDir:     envOrDefault("ENVD_OVERLAY_DIR", "/var/lib/envd/overlays"),
		CgroupRoot:     envOrDefault("ENVD_CGROUP_ROOT", "/sys/fs/cgroup/envd"),
	}
	return cfg
}

func main() {
	cfg := LoadConfig()
	configureLogging(cfg.LogLevel)

	log.WithFields(log.Fields{
		"grpc_addr":   cfg.GRPCAddr,
		"health_addr": cfg.HealthAddr,
		"workspace":   cfg.WorkspaceRoot,
		"firecracker": cfg.EnableFirecracker,
	}).Info("envd starting")

	// Initialize the sandbox manager.
	mgr, err := sandbox.NewManager(sandbox.ManagerConfig{
		MaxSandboxes:      cfg.MaxSandboxes,
		WorkspaceRoot:     cfg.WorkspaceRoot,
		EnableFirecracker: cfg.EnableFirecracker,
		FirecrackerBin:    cfg.FirecrackerBin,
		KernelImage:       cfg.KernelImage,
		RootfsImage:       cfg.RootfsImage,
		OverlayDir:        cfg.OverlayDir,
		CgroupRoot:        cfg.CgroupRoot,
	})
	if err != nil {
		log.Fatalf("failed to create sandbox manager: %v", err)
	}
	defer mgr.Shutdown()

	// Create a context that cancels on OS signals.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	var wg sync.WaitGroup

	// Start gRPC server.
	grpcServer := grpc.NewServer(
		grpc.MaxRecvMsgSize(64 << 20), // 64 MB
		grpc.MaxSendMsgSize(64 << 20),
	)
	server.RegisterSandboxService(grpcServer, mgr)

	grpcLis, err := net.Listen("tcp", cfg.GRPCAddr)
	if err != nil {
		log.Fatalf("failed to listen on %s: %v", cfg.GRPCAddr, err)
	}

	wg.Add(1)
	go func() {
		defer wg.Done()
		log.Infof("gRPC server listening on %s", cfg.GRPCAddr)
		if err := grpcServer.Serve(grpcLis); err != nil {
			log.Errorf("gRPC server error: %v", err)
		}
	}()

	// Start HTTP health server.
	healthServer := server.NewHealthServer(mgr, cfg.HealthAddr)

	wg.Add(1)
	go func() {
		defer wg.Done()
		log.Infof("health server listening on %s", cfg.HealthAddr)
		if err := healthServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Errorf("health server error: %v", err)
		}
	}()

	// Start sandbox health monitor.
	wg.Add(1)
	go func() {
		defer wg.Done()
		mgr.RunHealthMonitor(ctx, 10*time.Second)
	}()

	// Wait for shutdown signal.
	sig := <-sigCh
	log.Infof("received signal %v, shutting down", sig)
	cancel()

	// Graceful shutdown with timeout.
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer shutdownCancel()

	// Stop gRPC server gracefully.
	stopped := make(chan struct{})
	go func() {
		grpcServer.GracefulStop()
		close(stopped)
	}()

	select {
	case <-stopped:
		log.Info("gRPC server stopped gracefully")
	case <-shutdownCtx.Done():
		log.Warn("gRPC graceful stop timed out, forcing")
		grpcServer.Stop()
	}

	// Stop health server.
	if err := healthServer.Shutdown(shutdownCtx); err != nil {
		log.Errorf("health server shutdown error: %v", err)
	}

	// Destroy all sandboxes.
	mgr.DestroyAll()

	wg.Wait()
	log.Info("envd shutdown complete")
}

// configureLogging sets the log level and formatter.
func configureLogging(level string) {
	log.SetFormatter(&log.JSONFormatter{
		TimestampFormat: time.RFC3339Nano,
	})

	lvl, err := log.ParseLevel(level)
	if err != nil {
		lvl = log.InfoLevel
	}
	log.SetLevel(lvl)
}

// envOrDefault returns the environment variable value or a default.
func envOrDefault(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

// envOrDefaultInt returns the environment variable as int or a default.
func envOrDefaultInt(key string, defaultVal int) int {
	val := os.Getenv(key)
	if val == "" {
		return defaultVal
	}
	var result int
	if _, err := fmt.Sscanf(val, "%d", &result); err != nil {
		return defaultVal
	}
	return result
}
