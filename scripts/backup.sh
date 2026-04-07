#!/usr/bin/env bash
# backup.sh — Workspace backup for Horizon Orchestra.
# Backs up SQLite memory DBs, user workspace files, and configuration.
# Optionally uploads to S3.
set -euo pipefail

# --- Configuration ---
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/home/user/workspace}"
ORCHESTRA_HOME="${ORCHESTRA_HOME:-/opt/orchestra}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/orchestra}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-backups/orchestra}"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
BACKUP_NAME="orchestra-backup-${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
RETAIN_LOCAL_DAYS="${BACKUP_RETAIN_DAYS:-30}"

log_info()  { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [INFO]  $*"; }
log_error() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [ERROR] $*" >&2; }
log_warn()  { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [WARN]  $*"; }

# --- Setup ---
mkdir -p "${BACKUP_DIR}"
mkdir -p "${BACKUP_PATH}"

# --- Backup SQLite databases ---
backup_sqlite() {
    log_info "Backing up SQLite databases"
    local db_dir="${BACKUP_PATH}/databases"
    mkdir -p "${db_dir}"

    local count=0
    while IFS= read -r -d '' dbfile; do
        local dbname
        dbname=$(basename "${dbfile}")
        # Use SQLite online backup if sqlite3 is available.
        if command -v sqlite3 &>/dev/null; then
            sqlite3 "${dbfile}" ".backup '${db_dir}/${dbname}'" 2>/dev/null || {
                # Fallback: direct copy.
                cp "${dbfile}" "${db_dir}/${dbname}"
            }
        else
            cp "${dbfile}" "${db_dir}/${dbname}"
        fi
        count=$((count + 1))
    done < <(find "${ORCHESTRA_HOME}" "${WORKSPACE_ROOT}" -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" 2>/dev/null -print0 || true)

    log_info "  Backed up ${count} SQLite database(s)"
}

# --- Backup user workspace files ---
backup_workspace() {
    log_info "Backing up user workspace files"
    local ws_dir="${BACKUP_PATH}/workspace"
    mkdir -p "${ws_dir}"

    if [[ -d "${WORKSPACE_ROOT}" ]]; then
        # Exclude large/temporary directories.
        rsync -a --quiet \
            --exclude='node_modules/' \
            --exclude='__pycache__/' \
            --exclude='.git/' \
            --exclude='*.pyc' \
            --exclude='.venv/' \
            --exclude='target/' \
            "${WORKSPACE_ROOT}/" "${ws_dir}/" 2>/dev/null || {
                # Fallback if rsync not available.
                cp -r "${WORKSPACE_ROOT}" "${ws_dir}/" 2>/dev/null || true
            }
        local size
        size=$(du -sh "${ws_dir}" 2>/dev/null | cut -f1)
        log_info "  Workspace backup size: ${size}"
    else
        log_warn "  Workspace directory not found: ${WORKSPACE_ROOT}"
    fi
}

# --- Backup configuration ---
backup_config() {
    log_info "Backing up configuration"
    local cfg_dir="${BACKUP_PATH}/config"
    mkdir -p "${cfg_dir}"

    # Orchestra configuration.
    if [[ -d "${ORCHESTRA_HOME}/config" ]]; then
        cp -r "${ORCHESTRA_HOME}/config" "${cfg_dir}/orchestra/" 2>/dev/null || true
    fi

    # Environment files.
    for envfile in .env .env.local .env.production; do
        if [[ -f "${WORKSPACE_ROOT}/${envfile}" ]]; then
            cp "${WORKSPACE_ROOT}/${envfile}" "${cfg_dir}/${envfile}"
        fi
    done

    log_info "  Configuration backed up"
}

# --- Create compressed archive ---
create_archive() {
    log_info "Creating compressed archive"
    local archive="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
    tar -czf "${archive}" -C "${BACKUP_DIR}" "${BACKUP_NAME}"
    rm -rf "${BACKUP_PATH}"

    local size
    size=$(du -sh "${archive}" 2>/dev/null | cut -f1)
    log_info "  Archive created: ${archive} (${size})"
    echo "${archive}"
}

# --- Upload to S3 (optional) ---
upload_to_s3() {
    local archive="$1"

    if [[ -z "${S3_BUCKET}" ]]; then
        log_info "S3 upload skipped (S3_BUCKET not set)"
        return 0
    fi

    if ! command -v aws &>/dev/null; then
        log_warn "AWS CLI not found, skipping S3 upload"
        return 0
    fi

    local s3_key="${S3_PREFIX}/$(basename "${archive}")"
    log_info "Uploading to s3://${S3_BUCKET}/${s3_key}"

    if aws s3 cp "${archive}" "s3://${S3_BUCKET}/${s3_key}" --quiet; then
        log_info "  S3 upload complete"
    else
        log_error "  S3 upload failed"
        return 1
    fi
}

# --- Clean old local backups ---
clean_old_backups() {
    log_info "Cleaning backups older than ${RETAIN_LOCAL_DAYS} days"
    local count=0
    while IFS= read -r -d '' oldbackup; do
        rm -f "${oldbackup}"
        count=$((count + 1))
    done < <(find "${BACKUP_DIR}" -maxdepth 1 -name "orchestra-backup-*.tar.gz" -type f -mtime "+${RETAIN_LOCAL_DAYS}" -print0)

    if [[ ${count} -gt 0 ]]; then
        log_info "  Removed ${count} old backup(s)"
    fi
}

# --- Main ---
log_info "Orchestra backup starting"
log_info "Backup name: ${BACKUP_NAME}"

backup_sqlite
backup_workspace
backup_config
ARCHIVE=$(create_archive)
upload_to_s3 "${ARCHIVE}"
clean_old_backups

log_info "Backup completed successfully: ${ARCHIVE}"
