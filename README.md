# Apple Pay Merchant-Validation SSRF — A Bug Bounty Case Study

> How an unauthenticated Server-Side Request Forgery (SSRF) hid inside an Apple Pay
> checkout integration, and how it was found, proven, and ruled *in* (not just
> assumed) during a real bug bounty engagement.

**Status:** Disclosed to the affected vendor through a private bug bounty program.
Target identity, endpoint paths, and internal identifiers in this write-up have been
**genericized/redacted** — this repo documents the *methodology*, not a live,
unpatched target. Do not point any of the example commands at a system you don't
have explicit written authorization to test.

---

## TL;DR

A retail storefront running Salesforce Commerce Cloud (SFCC) exposed a custom Apple
Pay integration controller (`ApplePay-ValidateMerchant`) that took the client-supplied
`validationURL` from the [W3C Payment Request API](https://www.w3.org/TR/payment-request/)'s
`ApplePayValidateMerchantEvent` and used it, **unvalidated**, as the destination for a
server-side HTTP POST containing the merchant's real Apple Pay identity payload
(merchant ID, display name, domain). Apple's own integration guidance requires
merchants to verify that `validationURL` resolves to an Apple-owned domain before
using it — this check was missing, giving any unauthenticated visitor a way to make
the backend send authenticated-looking requests, carrying internal configuration
data, to an arbitrary attacker-controlled host.

Confirmed via out-of-band (OOB) HTTP interaction (not just a DNS ping), reproduced
independently twice with fresh collaborator domains, and ruled out against every
common SSRF false-positive cause before being reported.

## Why this write-up exists

Most public SSRF write-ups either show a payload firing or hand-wave "and then I
confirmed it." This one is deliberately narrated as a sequence of **experiments** —
recon, hypothesis, test, verify, rule-out-false-positive, reproduce — because the
verification discipline is the actually reusable part. The hunting approach here
borrows the "assume every finding is a hallucination until it survives verification"
philosophy from Andy Gill's (ZephrFish)
[*Jenny was a Friend of Mine — MCPs and Friends*](https://blog.zsec.uk/bullyingllms/)
write-up on autonomous vulnerability hunting: nothing gets called a finding until it's
proven with an out-of-band callback, not an assumption.

## Contents

- [`WALKTHROUGH.md`](./WALKTHROUGH.md) — the full experiment log: recon → discovery →
  root-cause analysis → OOB proof → false-positive ruling-out → reproducibility →
  impact-escalation attempt (including what *didn't* work and why that's reported
  honestly rather than inflated)
- [`WALKTHROUGH_SIMPLE.md`](./WALKTHROUGH_SIMPLE.md) — the same story in plain English,
  no jargon, with a hotel-front-desk analogy. Start here if you're new to SSRF or just
  want the fast, reviewable overview.
- [`poc/validate_merchant_ssrf.py`](./poc/validate_merchant_ssrf.py) — a generic,
  reusable PoC script (targets a placeholder host by default; requires you to pass
  your own authorized target)
- [`docs/sequence-diagram.md`](./docs/sequence-diagram.md) — the request/response
  chain diagram explaining why the endpoint returned an HTTP 500 *even though* the
  SSRF succeeded

## Vulnerability class background

Apple's own Apple Pay JS documentation is explicit that a merchant's backend must
treat `validationURL` as **untrusted input from the browser** and verify it belongs to
one of Apple's payment-gateway domains before calling it — precisely to prevent this
class of bug. This is a known, recurring anti-pattern: several public disclosures
exist for "Apple Pay merchant validation SSRF" across different e-commerce platforms.
It's a good example of a vulnerability that's invisible from the outside (no visible
parameter reflection, no error-based oracle) and only surfaces once you trace a
specific client-side event handler down to its backend sink.

## Tooling used

Recon and discovery: `subfinder`, `httpx`, `katana`, `gau`, `arjun`, `nuclei`.
Verification: `interactsh-client` for OOB HTTP/DNS interaction, plain `curl` for
precise, minimal-request PoC delivery (no scanners fired at the live target beyond
initial discovery — every confirmatory step was a single, hand-crafted request).

## Responsible disclosure

This finding was reported to the affected vendor through their private bug bounty
program before this write-up was published. Real target details are withheld here
until the vendor confirms remediation and authorizes public disclosure, per standard
coordinated-disclosure practice.

## License

Write-up and PoC code: MIT (see [`LICENSE`](./LICENSE)). This is educational
material — use only against systems you are explicitly authorized to test.
