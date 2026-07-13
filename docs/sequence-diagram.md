# Why the HTTP 500 doesn't contradict the SSRF

A natural question when reading the walkthrough: if the vulnerable endpoint returned
an HTTP 500 error to the tester, how can the SSRF be confirmed at all? The answer is
that the 500 and the SSRF are two different steps in the same chain — one failing
doesn't undo the other having already happened.

## Two independent vantage points

Only two things are directly observed by the tester:

- **(A)** What the tester's own HTTP client sees: one request/response pair, sent
  straight to the target.
- **(B)** What the tester's own OOB collaborator server sees: one request/response
  pair, received on infrastructure only the tester controls.

Neither alone proves SSRF. What proves it is that **(B) happened at all** — nothing on
the tester's side ever contacted the collaborator domain directly. The only way that
domain receives a hit is if a third party (the target's backend) independently
resolved and connected to it.

## The full chain, reconstructed from both vantage points

```
 [1] tester ──POST /ApplePay-ValidateMerchant──▶  target backend
       body: {"validationURL":"https://<collaborator-domain>/poc", "hostname":"..."}

 [2]                                    target backend:
                                        - parses the JSON body
                                        - reads validationURL (no domain check)
                                        - builds the REAL Apple Pay merchant-session
                                          request payload:
                                          {"merchantIdentifier": "...",
                                           "displayName": "...",
                                           "domainName": "..."}

 [3]                    target backend ──POST /poc──▶  tester's OOB collaborator
                         (hop captured independently, on infra the target
                          backend's own HTTP client connected to)

 [4]                    tester's OOB collaborator ──HTTP 200, text/html──▶  target backend
                         body: "<html>...dummy token...</html>"
                         (a real Apple server would instead return a JSON
                          "merchant session" object)

 [5]                                    target backend:
                                        - expects step [4]'s reply to be a JSON
                                          merchant-session object with a specific
                                          schema (epoch timestamp, merchant session
                                          identifier, signature, etc.)
                                        - tries to parse the dummy HTML as that schema
                                        - parsing/deserialization throws
                                        - generic catch-all handler fires

 [6] tester ◀──HTTP 500, {"error":"Unknown error"}──  target backend
```

## Why the 500 actually corroborates the finding

Step [1] → [6] is the only thing directly visible end-to-end from the tester's own
request. Steps [2]–[5] happen inside the target's infrastructure and are invisible
from that side alone — but step [3] is exactly what the OOB collaborator capture
proved happened, from a completely independent vantage point, correlated by:

- a unique, freshly generated collaborator subdomain that only the tester possessed
- a request landing within about a second of the trigger request
- payload content (the real merchant identifier) that only the target application's
  own code could have produced

So the 500 is exactly what you'd expect to see **because** the SSRF succeeded: the
backend fetched the attacker-supplied URL, got back something that wasn't a valid
Apple merchant session, and threw trying to process it. If the vulnerable code path
didn't exist — if `validationURL` were validated against an allowlist of Apple
domains before being fetched — the request would have been rejected *before* any
outbound call, and the collaborator would have received nothing at all.

This is also why response timing and body content couldn't be used to infer whether
the SSRF reaches internal-network or cloud-metadata addresses (see the write-up's
impact-escalation section): every non-Apple-shaped outcome — a successful fetch of an
unexpected response, a blocked connection, an unreachable host — collapses into the
same generic error at step [5]/[6]. The *external*, internet-reachable case is
unambiguous because it was independently observed at step [3]; the *internal*
case has no equivalent independent observation point, so it's reported as
inconclusive rather than inferred from an unreliable signal.
