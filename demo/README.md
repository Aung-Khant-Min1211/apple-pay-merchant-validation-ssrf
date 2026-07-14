# Live Demo — Apple Pay ValidateMerchant SSRF

A **fully local, safe** reproduction of the finding. It runs the *real* PoC
script (`../poc/validate_merchant_ssrf.py`) against a mock storefront on your own
machine, so you can show the SSRF actually firing — without ever touching the
real (still-under-disclosure) target.

Everything binds to `127.0.0.1`. Nothing external is contacted.

## What's in here

| File | Role in the demo |
|---|---|
| `vulnerable_server.py` | Mock SFCC storefront with the vulnerable `ApplePay-ValidateMerchant` controller. Stands in for the target backend. |
| `collaborator.py` | Local out-of-band listener — the role interactsh / Burp Collaborator played in the real hunt. Any hit here = proof of SSRF. |
| `run_demo.sh` | Starts both, fires the PoC, and prints the captured callback. |

## Run it

```bash
cd demo
./run_demo.sh            # vulnerable controller: SSRF fires, callback captured
./run_demo.sh --secure   # patched controller: request rejected, NO callback (the fix)
```

Requires only `python3` (standard library — no pip installs).

## The three moving parts (say this out loud during the demo)

```
  PoC script            mock storefront (:8080)          collaborator (:9000)
  "the attacker"        "the target backend"             "a host only I control"
       │                        │                                │
       │  1. GET /cart          │                                │
       │───────────────────────▶│  (gets a session cookie)       │
       │                        │                                │
       │  2. POST ValidateMerchant                               │
       │     validationURL = http://:9000/poc                    │
       │───────────────────────▶│                                │
       │                        │  3. backend does NOT validate  │
       │                        │     the URL, and POSTs the     │
       │                        │     merchant identity payload  │
       │                        │───────────────────────────────▶│  ← THE PROOF
       │                        │                                │
       │                        │  4. collaborator returns HTML  │
       │                        │◀───────────────────────────────│
       │                        │  5. backend can't parse it as  │
       │  6. HTTP 500           │     an Apple session → throws  │
       │◀───────────────────────│                                │
```

## The key talking point

The PoC's own output shows an **HTTP 500 "Unknown error"** — which *looks* like a
failure. It isn't. The proof of the vulnerability is on the **collaborator**: the
storefront backend independently reached out to a host it should never contact and
**leaked the merchant identity payload** in the request body. Nothing on the
attacker's side ever contacted that host directly — the only way it gets a hit is
if the target's own backend made the request. That's the SSRF.

Then run `--secure` to show the one-line fix: validate `validationURL` against an
allowlist of Apple domains *before* fetching it. The request is rejected with a
403 and the collaborator receives nothing — no SSRF.

## Why this is safe to present

- No real target host, endpoint, or identifier appears anywhere — the merchant
  payload is a generic placeholder (`merchant.com.demo.storefront`).
- Both servers are localhost-only; the demo cannot reach the internet.
- It demonstrates the *vulnerability class and verification method*, which is
  exactly what the parent repo documents.
