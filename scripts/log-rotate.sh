#!/usr/bin/env bash
# log-rotate.sh — Log rotation for Horizon Orchestra services.
# Rotates Python, Node, and Go logs, compresses old logs, retains 7 days.
set -euo pipefail

# --- Configuration ---
LOG_DIR="${LOG_DIR:-/var/log/orchestra}"
RETAIN_DAYS="${LOG_RETAIN_DAYS:-7}"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

log_info() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [INFO]  $*"; }
log_warn() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [WARN]  $*"; }

# --- Service log directories ---
declare -a LOG_DIRS=(
    "${LOG_DIR}/python"
    "${LOG_DIR}/node"
    "${LOG_DIR}/go"
)

# --- Ensure directories exist ---
for dir in "${LOG_DIRS[@]}"; do
    mkdir -p "${dir}"
done

# --- Rotate logs ---
rotate_logs() {
    local dir="$1"
    local service_name
    service_name=$(basename "${dir}")

    log_info "Rotating logs in ${dir} (service: ${service_name})"

    # Find active log files (not already compressed).
    while IFS= read -r -d '' logfile; do
        local basename_file
        basename_file=$(basename "${logfile}")
        local rotated="${logfile}.${TIMESTAMP}"

        # Rotate: rename current log to timestamped version.
        if [[ -s "${logfile}" ]]; then
            cp "${logfile}" "${rotated}"
            : > "${logfile}"  # Truncate the original.
            log_info "  Rotated: ${basename_file} -> ${basename_file}.${TIMESTAMP}"

            # Compress the rotated log.
            gzip "${rotated}"
            log_info "  Compressed: ${basename_file}.${TIMESTAMP}.gz"
        fi
    done < <(find "${dir}" -maxdepth 1 -name "*.log" -type f -print0)
}

# --- Clean old logs ---
clean_old_logs() {
    local dir="$1"
    local count=0

    while IFS= read -r -d '' oldfile; do
        rm -f "${oldfile}"
        count=$((count + 1))
    done < <(find "${dir}" -maxdepth 1 -name "*.gz" -type f -mtime "+${RETAIN_DAYS}" -print0)

    if [[ ${count} -gt 0 ]]; then
        log_info "  Cleaned ${count} old compressed log(s) from ${dir}"
    fi
}

# --- Main ---
log_info "Starting log rotation (retain ${RETAIN_DAYS} days)"

for dir in "${LOG_DIRS[@]}"; do
    if [[ -d "${dir}" ]]; then
        rotate_logs "${dir}"
        clean_old_logs "${dir}"
    else
        log_warn "Directory not found: ${dir}"
    fi
done

# --- Disk usage report ---
log_info "Log directory disk usage:"
for dir in "${LOG_DIRS[@]}"; do
    if [[ -d "${dir}" ]]; then
        size=$(du -sh "${dir}" 2>/dev/null | cut -f1)
        count=$(find "${dir}" -type f | wc -l)
        log_info "  ${dir}: ${size} (${count} files)"
    fi
done

log_info "Log rotation complete"
