#!/usr/bin/env bash
# bootstrap.sh — Full sandbox environment bootstrap for Horizon Orchestra.
# Installs Python 3.12, Node.js 22, Go 1.22, Rust toolchain, system tools,
# Python packages, and sets up the workspace directory structure.
set -euo pipefail

# --- Configuration ---
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/home/user/workspace}"
ORCHESTRA_HOME="${ORCHESTRA_HOME:-/opt/orchestra}"
LOG_DIR="${LOG_DIR:-/var/log/orchestra}"
PYTHON_VERSION="3.12"
NODE_VERSION="22"
GO_VERSION="1.22.4"
RUST_CHANNEL="stable"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Pre-flight checks ---
log_info "Horizon Orchestra bootstrap starting"
log_info "Workspace: ${WORKSPACE_ROOT}"
log_info "Orchestra home: ${ORCHESTRA_HOME}"

if [[ $EUID -ne 0 ]]; then
    SUDO="sudo"
    log_warn "Not running as root, will use sudo"
else
    SUDO=""
fi

# --- System packages ---
log_info "Updating package lists"
$SUDO apt-get update -qq

log_info "Installing base system packages"
$SUDO apt-get install -y -qq \
    build-essential \
    curl \
    wget \
    git \
    unzip \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    jq \
    tmux \
    htop \
    strace

# --- Python 3.12 ---
log_info "Installing Python ${PYTHON_VERSION}"
$SUDO add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq \
    "python${PYTHON_VERSION}" \
    "python${PYTHON_VERSION}-venv" \
    "python${PYTHON_VERSION}-dev" \
    "python${PYTHON_VERSION}-distutils" || {
    log_warn "PPA install failed, trying system python3"
}

# Ensure pip is available.
if ! command -v pip3 &>/dev/null; then
    curl -sSL https://bootstrap.pypa.io/get-pip.py | "python${PYTHON_VERSION}"
fi

# Set python3 alternative.
$SUDO update-alternatives --install /usr/bin/python3 python3 "/usr/bin/python${PYTHON_VERSION}" 1 2>/dev/null || true

log_info "Python version: $(python3 --version)"

# --- Node.js 22 ---
log_info "Installing Node.js ${NODE_VERSION}"
if ! command -v node &>/dev/null || [[ "$(node -v)" != v${NODE_VERSION}* ]]; then
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | $SUDO bash -
    $SUDO apt-get install -y -qq nodejs
fi
log_info "Node.js version: $(node --version)"
log_info "npm version: $(npm --version)"

# Install global Node packages.
$SUDO npm install -g yarn pnpm typescript ts-node

# --- Go 1.22 ---
log_info "Installing Go ${GO_VERSION}"
GO_ARCHIVE="go${GO_VERSION}.linux-amd64.tar.gz"
if ! command -v go &>/dev/null || [[ "$(go version)" != *"go${GO_VERSION}"* ]]; then
    wget -q "https://go.dev/dl/${GO_ARCHIVE}" -O "/tmp/${GO_ARCHIVE}"
    $SUDO rm -rf /usr/local/go
    $SUDO tar -C /usr/local -xzf "/tmp/${GO_ARCHIVE}"
    rm -f "/tmp/${GO_ARCHIVE}"
fi
export PATH="/usr/local/go/bin:${PATH}"
log_info "Go version: $(go version)"

# --- Rust toolchain ---
log_info "Installing Rust (${RUST_CHANNEL})"
if ! command -v rustup &>/dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain "${RUST_CHANNEL}"
fi
# shellcheck source=/dev/null
source "${HOME}/.cargo/env" 2>/dev/null || true
rustup default "${RUST_CHANNEL}"
rustup update "${RUST_CHANNEL}"
log_info "Rust version: $(rustc --version)"
log_info "Cargo version: $(cargo --version)"

# --- Media & document tools ---
log_info "Installing ffmpeg, yt-dlp, mat2, pandoc, imagemagick, ghostscript"
$SUDO apt-get install -y -qq \
    ffmpeg \
    pandoc \
    imagemagick \
    ghostscript \
    mat2 \
    poppler-utils \
    tesseract-ocr \
    libmagic1 || log_warn "Some media tools could not be installed"

# Install yt-dlp via pip (latest version).
pip3 install --quiet --upgrade yt-dlp

# --- Python packages ---
log_info "Installing Python packages (orchestra + extras)"
pip3 install --quiet --upgrade \
    pip \
    setuptools \
    wheel

pip3 install --quiet \
    fastapi \
    uvicorn \
    httpx \
    aiohttp \
    websockets \
    grpcio \
    grpcio-tools \
    protobuf \
    pydantic \
    redis \
    asyncpg \
    sqlalchemy \
    alembic \
    celery \
    tiktoken \
    openai \
    anthropic \
    numpy \
    scipy \
    pandas \
    scikit-learn \
    pillow \
    beautifulsoup4 \
    lxml \
    pyyaml \
    toml \
    python-dotenv \
    click \
    rich \
    tqdm \
    pytest \
    pytest-asyncio \
    mypy \
    ruff \
    maturin

log_info "Python packages installed"

# --- Workspace directory structure ---
log_info "Setting up workspace directory structure"
mkdir -p "${WORKSPACE_ROOT}"
mkdir -p "${ORCHESTRA_HOME}"/{config,data,cache,logs,tmp}
mkdir -p "${LOG_DIR}"/{python,node,go}
mkdir -p "${WORKSPACE_ROOT}"/space_files

# --- Environment variables ---
log_info "Configuring environment variables"
ENV_FILE="${ORCHESTRA_HOME}/config/orchestra.env"
cat > "${ENV_FILE}" << 'ENVEOF'
# Horizon Orchestra Environment Configuration
export ORCHESTRA_HOME=/opt/orchestra
export WORKSPACE_ROOT=/home/user/workspace
export LOG_DIR=/var/log/orchestra

# Python
export PYTHONPATH=/opt/orchestra/python:${PYTHONPATH:-}
export PYTHONDONTWRITEBYTECODE=1

# Node.js
export NODE_ENV=production
export NODE_OPTIONS="--max-old-space-size=4096"

# Go
export GOPATH=/opt/orchestra/go
export PATH="/usr/local/go/bin:${GOPATH}/bin:${PATH}"

# Rust
export CARGO_HOME=${HOME}/.cargo
export PATH="${CARGO_HOME}/bin:${PATH}"

# envd
export ENVD_GRPC_ADDR=:50051
export ENVD_HEALTH_ADDR=:8081
export ENVD_WORKSPACE_ROOT=/home/user/workspace
export ENVD_MAX_SANDBOXES=16
export ENVD_LOG_LEVEL=info

# Redis
export REDIS_URL=redis://localhost:6379/0

# PostgreSQL
export DATABASE_URL=postgresql://orchestra:orchestra@localhost:5432/orchestra
ENVEOF

# Add to shell profile.
PROFILE_LINE="source ${ENV_FILE}"
for RC_FILE in "${HOME}/.bashrc" "${HOME}/.profile"; do
    if [[ -f "${RC_FILE}" ]] && ! grep -qF "${PROFILE_LINE}" "${RC_FILE}"; then
        echo "${PROFILE_LINE}" >> "${RC_FILE}"
    fi
done

# --- Verification ---
log_info "Verifying installations"
ERRORS=0

for cmd in python3 node npm go rustc cargo ffmpeg pandoc convert gs; do
    if command -v "${cmd}" &>/dev/null; then
        log_info "  ✓ ${cmd} found"
    else
        log_error "  ✗ ${cmd} not found"
        ERRORS=$((ERRORS + 1))
    fi
done

if [[ ${ERRORS} -gt 0 ]]; then
    log_warn "Bootstrap completed with ${ERRORS} error(s)"
    exit 1
fi

log_info "Bootstrap completed successfully"
log_info "Source the environment: source ${ENV_FILE}"
