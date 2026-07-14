#!/usr/bin/env bash
#
# Paced driver used to record the asciinema capture (demo.cast). It runs the two
# real demo scenarios back-to-back with reading pauses so the recording is
# watchable in a presentation. It changes nothing about the demo itself.
#
#   asciinema rec demo/demo.cast --command "bash demo/record_demo.sh"

set -u
cd "$(dirname "$0")/.."
PAUSE_READ=5   # seconds to let a result sit on screen
PAUSE_BEAT=2   # short beat between phases

banner() { printf '\n\033[1;36m%s\033[0m\n\n' "$*"; }

banner ">>> Apple Pay ValidateMerchant SSRF — live proof-of-concept demo"
sleep "$PAUSE_BEAT"

banner ">>> SCENARIO 1: the VULNERABLE storefront  (the SSRF fires)"
sleep "$PAUSE_BEAT"
bash demo/run_demo.sh
sleep "$PAUSE_READ"

banner ">>> SCENARIO 2: the PATCHED storefront  (validationURL rejected — no SSRF)"
sleep "$PAUSE_BEAT"
bash demo/run_demo.sh --secure
sleep "$PAUSE_READ"

banner ">>> Recap: same PoC, same request. Vulnerable = secret leaked to our"
banner "    collaborator. Patched = rejected before any outbound call. That's the bug,"
banner "    and that's the one-line fix."
sleep "$PAUSE_BEAT"
