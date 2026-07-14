#!/usr/bin/env python3
"""
Local stand-in for an out-of-band (OOB) collaborator -- the role interactsh /
Burp Collaborator played in the real engagement. It is infrastructure ONLY the
tester controls; the target's backend has no legitimate reason to contact it.

Any inbound request here is the proof of SSRF: nothing on the tester's side
contacted this listener directly -- the only way it gets a hit is if a third
party (the target backend) resolved and connected to it.

For each hit it prints a timestamp, method, path, headers and body, then returns
a dummy HTML "token" (mirroring sequence-diagram step [4]) so the target backend
gets a non-Apple-shaped reply and throws its generic 500.

Hits are also appended to demo/collaborator_hits.log so the demo can show them
after the run.
"""

import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PATH = "collaborator_hits.log"


class Handler(BaseHTTPRequestHandler):
    server_version = "OOB-Collaborator/1.0"

    def log_message(self, *a):
        pass  # we print our own, richer record

    def _record(self, method):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        ts = datetime.now().isoformat(timespec="milliseconds")

        lines = [
            "",
            "=" * 68,
            f"  [!] OOB CALLBACK RECEIVED  {ts}",
            "=" * 68,
            f"  {method} {self.path}",
            f"  From:  {self.client_address[0]}:{self.client_address[1]}",
        ]
        for k, v in self.headers.items():
            lines.append(f"  {k}: {v}")
        if body:
            lines.append("  ---- body (leaked by target backend) ----")
            lines.append("  " + body)
        lines.append("=" * 68)
        record = "\n".join(lines)

        print(record, file=sys.stderr, flush=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(record + "\n")

        # Return HTML, NOT an Apple merchant-session JSON object.
        reply = b"<html><body>dummy-collaborator-token</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def do_GET(self):
        self._record("GET")

    def do_POST(self):
        self._record("POST")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    # Truncate the log at startup so each demo run is clean.
    open(LOG_PATH, "w").close()
    print(f"[collaborator] OOB listener on :{port}  (logging to {LOG_PATH})",
          file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
