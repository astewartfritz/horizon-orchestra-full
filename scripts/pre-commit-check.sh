#!/usr/bin/env bash
# Horizon Orchestra — Pre-commit secret scanner
# Blocks commits containing API keys, passwords, or credentials.
# Install: cp scripts/pre-commit-check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

FAIL=0

# ── Patterns that indicate a leaked secret ───────────────────────────────────
declare -a PATTERNS=(
  # API keys
  'sk-[a-zA-Z0-9]{32,}'                          # OpenAI
  'moonshot-[a-zA-Z0-9_-]{32,}'                  # Moonshot
  'pplx-[a-zA-Z0-9]{32,}'                        # Perplexity
  'AIza[0-9A-Za-z\\-_]{35}'                      # Google API key
  'AKIA[0-9A-Z]{16}'                             # AWS access key
  'eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'  # JWT token (long)
  # Generic patterns
  'password\s*=\s*["\x27][^\x27"]{8,}'
  'secret\s*=\s*["\x27][^\x27"]{8,}'
  'api_key\s*=\s*["\x27][^\x27"]{8,}'
  'private_key\s*=\s*["\x27][^\x27"]{8,}'
  'access_token\s*=\s*["\x27][^\x27"]{8,}'
  'webhook.*https://hooks\.'
  # SSH private keys
  '-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----'
  # Stripe
  'sk_live_[0-9a-zA-Z]{24,}'
  'rk_live_[0-9a-zA-Z]{24,}'
  # Twilio / SendGrid
  'SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}'
)

# Files to check (staged)
STAGED=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)

if [ -z "$STAGED" ]; then
  exit 0
fi

echo -e "${YELLOW}[pre-commit] Scanning staged files for secrets...${NC}"

for FILE in $STAGED; do
  # Skip binary files
  if ! file "$FILE" | grep -q "text\|ASCII\|UTF"; then
    continue
  fi

  for PATTERN in "${PATTERNS[@]}"; do
    if git diff --cached "$FILE" | grep -qE "$PATTERN" 2>/dev/null; then
      echo -e "${RED}✗ BLOCKED: Potential secret in staged file: $FILE${NC}"
      echo -e "  Pattern matched: ${YELLOW}${PATTERN}${NC}"
      FAIL=1
    fi
  done
done

# Block .env files (non-example)
for FILE in $STAGED; do
  if echo "$FILE" | grep -qE "^\.env$|^\.env\.[^e]|secrets|credentials|private_key"; then
    echo -e "${RED}✗ BLOCKED: Sensitive file staged: $FILE${NC}"
    FAIL=1
  fi
done

if [ "$FAIL" -eq 1 ]; then
  echo ""
  echo -e "${RED}╔════════════════════════════════════════════════╗${NC}"
  echo -e "${RED}║  COMMIT BLOCKED — Potential secret detected.  ║${NC}"
  echo -e "${RED}║  Remove the secret and use .env instead.      ║${NC}"
  echo -e "${RED}╚════════════════════════════════════════════════╝${NC}"
  exit 1
fi

echo -e "${GREEN}✓ No secrets detected. Proceeding with commit.${NC}"
exit 0
