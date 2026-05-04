#!/bin/bash
# Horizon Orchestra installer
# curl -fsSL https://get.horizonorchestra.dev | sh

set -euo pipefail

REPO_URL="${HORIZON_REPO_URL:-https://github.com/astewartfritz/horizon-orchestra.git}"
INSTALL_DIR="${HORIZON_INSTALL_DIR:-$HOME/.horizon-orchestra}"
BIN_DIR="${HORIZON_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_DIR/.venv"
SHELL_RC="$HOME/.zshrc"
[ -f "$HOME/.bashrc" ] && SHELL_RC="$HOME/.bashrc"

echo ""
echo "Horizon Orchestra"
echo "----------------------------------------"

for dep in python3 git; do
  if ! command -v "$dep" >/dev/null 2>&1; then
    echo "ERROR: $dep is required. Please install it first."
    exit 1
  fi
done

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "Updating existing installation..."
  git -C "$INSTALL_DIR" pull --quiet --ff-only
else
  echo "Cloning repository..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

echo "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
  "$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
fi

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/horizon" <<EOF
#!/bin/bash
exec "$VENV_DIR/bin/python" "$INSTALL_DIR/horizon.py" "\$@"
EOF
chmod +x "$BIN_DIR/horizon"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo "" >> "$SHELL_RC"
    echo "# Horizon Orchestra" >> "$SHELL_RC"
    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_RC"
    export PATH="$BIN_DIR:$PATH"
    ;;
esac

echo ""
echo "Installed. Launching setup..."
echo ""

exec "$BIN_DIR/horizon" init
