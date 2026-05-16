package server

import (
	"encoding/json"
	"net/http"
	"sync/atomic"
	"time"

	log "github.com/sirupsen/logrus"

	"github.com/astewartfritz/horizon-orchestra/go/envd/sandbox"
)

// ready is an atomic flag indicating whether the server is ready to serve traffic.
var ready atomic.Bool

// NewHealthServer creates an HTTP server with health and readiness endpoints.
func NewHealthServer(mgr *sandbox.Manager, addr string) *http.Server {
	mux := http.NewServeMux()

	// Liveness probe — always returns 200 if the process is up.
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status":    "alive",
			"timestamp": time.Now().UTC().Format(time.RFC3339Nano),
		})
	})

	// Readiness probe — returns 200 only when the service is ready to handle requests.
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if !ready.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"status": "not_ready",
			})
			return
		}

		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status":    "ready",
			"timestamp": time.Now().UTC().Format(time.RFC3339Nano),
		})
	})

	// Detailed status endpoint with sandbox manager health.
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")

		hs := mgr.HealthStatus()
		hs["uptime_seconds"] = int64(time.Since(startTime).Seconds())
		hs["timestamp"] = time.Now().UTC().Format(time.RFC3339Nano)

		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(hs)
	})

	// Metrics endpoint (Prometheus-compatible text format placeholder).
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		hs := mgr.HealthStatus()

		totalSandboxes, _ := hs["total_sandboxes"].(int)
		healthySandboxes, _ := hs["healthy_sandboxes"].(int)
		maxSandboxes, _ := hs["max_sandboxes"].(int)
		uptime := int64(time.Since(startTime).Seconds())

		fmt := "# HELP envd_sandboxes_total Current number of sandboxes\n" +
			"# TYPE envd_sandboxes_total gauge\n" +
			"envd_sandboxes_total %d\n" +
			"# HELP envd_sandboxes_healthy Number of healthy sandboxes\n" +
			"# TYPE envd_sandboxes_healthy gauge\n" +
			"envd_sandboxes_healthy %d\n" +
			"# HELP envd_sandboxes_max Maximum sandbox capacity\n" +
			"# TYPE envd_sandboxes_max gauge\n" +
			"envd_sandboxes_max %d\n" +
			"# HELP envd_uptime_seconds Uptime in seconds\n" +
			"# TYPE envd_uptime_seconds counter\n" +
			"envd_uptime_seconds %d\n"

		w.Write([]byte(formatMetrics(fmt, totalSandboxes, healthySandboxes, maxSandboxes, uptime)))
	})

	// Mark as ready once the server is configured.
	ready.Store(true)
	log.Info("health server configured with /healthz, /readyz, /status, /metrics")

	return &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}
}

// formatMetrics is a simple sprintf wrapper for metrics formatting.
func formatMetrics(format string, args ...interface{}) string {
	result := format
	for i, arg := range args {
		placeholder := "%d"
		_ = i
		_ = placeholder
		// Simple replacement — in production, use proper formatting.
		switch v := arg.(type) {
		case int:
			result = replaceFirst(result, "%d", intToStr(v))
		case int64:
			result = replaceFirst(result, "%d", int64ToStr(v))
		}
	}
	return result
}

// replaceFirst replaces the first occurrence of old with new in s.
func replaceFirst(s, old, new string) string {
	for i := 0; i <= len(s)-len(old); i++ {
		if s[i:i+len(old)] == old {
			return s[:i] + new + s[i+len(old):]
		}
	}
	return s
}

// intToStr converts an int to its string representation.
func intToStr(n int) string {
	if n == 0 {
		return "0"
	}
	neg := false
	if n < 0 {
		neg = true
		n = -n
	}
	digits := make([]byte, 0, 10)
	for n > 0 {
		digits = append(digits, byte('0'+n%10))
		n /= 10
	}
	if neg {
		digits = append(digits, '-')
	}
	// Reverse.
	for i, j := 0, len(digits)-1; i < j; i, j = i+1, j-1 {
		digits[i], digits[j] = digits[j], digits[i]
	}
	return string(digits)
}

// int64ToStr converts an int64 to its string representation.
func int64ToStr(n int64) string {
	return intToStr(int(n))
}
