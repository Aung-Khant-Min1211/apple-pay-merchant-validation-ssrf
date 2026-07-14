#!/usr/bin/env python3
"""
Mock vulnerable Salesforce Commerce Cloud (SFCC) storefront that reproduces the
`ApplePay-ValidateMerchant` SSRF for a SAFE, LOCAL demo. No real target is ever
touched. Run this on your own machine and point the PoC at it.

Two routes:
  GET  /en-us/cart                        -> a normal page that sets a session cookie
  POST /.../ApplePay-ValidateMerchant     -> the vulnerable controller

The controller mirrors the real bug:
  1. Parses the JSON body and reads `validationURL`.
  2. In DEFAULT (vulnerable) mode it does NOT validate that validationURL is an
     Apple-owned domain -- it builds the real merchant-session payload and POSTs
     it to whatever URL the client supplied (the SSRF hop).
  3. It then tries to parse the reply as an Apple merchant session; the demo
     collaborator returns HTML, parsing fails, and the controller returns a
     generic HTTP 500 -- exactly the "500 even though the SSRF fired" behaviour
     documented in docs/sequence-diagram.md.

Pass --secure to show the FIX: validationURL is checked against an allowlist of
Apple domains and rejected (HTTP 403) BEFORE any outbound request -- so the
collaborator receives nothing.
"""

import argparse
import json
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Genericized merchant identity -- stand-in for whatever the real backend would
# have leaked. Contains NO real target data.
MERCHANT_PAYLOAD = {
    "merchantIdentifier": "merchant.com.demo.storefront",
    "displayName": "Demo Storefront",
    "domainName": "demo-storefront.local",
    "initiative": "web",
    "initiativeContext": "demo-storefront.local",
}

# Apple's payment-gateway domains. The secure controller requires validationURL
# to belong to one of these before it will fetch it.
APPLE_ALLOWLIST = ("apple-pay-gateway.apple.com", "apple.com")

SECURE_MODE = False


def _host_of(url):
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def _is_apple_domain(url):
    host = _host_of(url)
    return any(host == d or host.endswith("." + d) for d in APPLE_ALLOWLIST)


class Handler(BaseHTTPRequestHandler):
    server_version = "SFCC-Demo/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("    [target] " + (fmt % args) + "\n")

    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Any GET hands out a session cookie, like a real storefront page.
        body = b"<html><body>Demo storefront cart</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "dwsid=demo-session-abc123; Path=/; HttpOnly")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if "ApplePay-ValidateMerchant" not in self.path:
            self._json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "Bad JSON"})
            return

        validation_url = data.get("validationURL", "")
        if not validation_url:
            self._json(400, {"error": "Missing validationURL"})
            return

        # ---- THE FIX (only in --secure mode) --------------------------------
        if SECURE_MODE and not _is_apple_domain(validation_url):
            sys.stderr.write(
                f"    [target] SECURE: rejected non-Apple validationURL "
                f"{validation_url!r} BEFORE any outbound call\n"
            )
            self._json(403, {"error": "validationURL is not an Apple domain"})
            return
        # ---------------------------------------------------------------------

        # ---- THE BUG: unvalidated server-side request (SSRF) ----------------
        sys.stderr.write(
            f"    [target] fetching attacker-supplied validationURL -> {validation_url}\n"
        )
        try:
            req = urllib.request.Request(
                validation_url,
                data=json.dumps(MERCHANT_PAYLOAD).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                reply = resp.read()
            # Backend expects an Apple "merchant session" JSON object here.
            session = json.loads(reply)  # collaborator returns HTML -> throws
            self._json(200, {"merchantSession": session})
        except Exception:
            # Generic catch-all -> exactly the 500 the real target returned.
            self._json(500, {"error": "Unknown error"})


def main():
    global SECURE_MODE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--secure", action="store_true",
                    help="Run the PATCHED controller (validates validationURL).")
    args = ap.parse_args()
    SECURE_MODE = args.secure

    mode = "SECURE (patched)" if SECURE_MODE else "VULNERABLE"
    print(f"[target] mock SFCC storefront listening on :{args.port}  mode={mode}",
          file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
