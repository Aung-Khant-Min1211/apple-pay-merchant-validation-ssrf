# The SSRF Finding, Explained Simply

> A plain-English companion to [`WALKTHROUGH.md`](./WALKTHROUGH.md). Same story, no
> jargon. If you've never heard of SSRF, start here. A reviewer should be able to read
> this top-to-bottom and understand *what* the bug is, *how* we found it, and *how* we
> proved it — in about ten minutes.
>
> Target details are genericized (placeholders like `shop.example.com`) because the
> finding is still under coordinated disclosure. The *method* is the real thing.

---

## 1. The whole thing in one sentence

We found a way to make someone else's online store secretly send a message —
carrying its own private information — to **our** computer, just by asking it nicely.
That's the bug. It's called **SSRF**.

## 2. First, a picture you already understand

Imagine a **hotel front desk**.

- You (a guest) hand the receptionist a note and say: *"Please call this phone number
  and read them our hotel's secret account details."*
- A **careful** receptionist says: *"I only call numbers on the official hotel list.
  This number isn't on it — no."*
- A **careless** receptionist just... dials the number and reads out the secrets.

**SSRF is a careless receptionist.** You (the attacker) can't see the hotel's secret
account details yourself, and you can't make the call from the hotel's phone. But you
can *trick the receptionist into doing it for you* — and the phone number you write on
the note is your own.

In our case:
- **You** = any random visitor to the website.
- **The receptionist** = the store's back-end server.
- **The note with a phone number** = a web address (a URL) we get to choose.
- **The secret account details** = the store's private payment identity.

## 3. Why did the store have a "please call this number" feature at all?

Because of **Apple Pay**.

When you pay with Apple Pay on a website, there's a required security handshake:

1. Apple tells your browser: *"To prove this store is really allowed to take Apple Pay,
   have the store's server call this special Apple web address."* (Apple calls it the
   `validationURL`.)
2. The store's server is supposed to call that Apple address and get back a
   "yes, they're legit" ticket.

Here's the catch that Apple **warns every developer about, in writing**:

> The web address in step 1 comes *through the visitor's browser*. A visitor could
> swap it for a fake one. So before your server calls it, **check that it's really an
> Apple address.**

Our store... forgot to check. It just called whatever address showed up. That's the
careless receptionist.

## 4. How we actually found it (the detective work)

We didn't get lucky. We followed a trail. Here's the trail, in order.

### Step 0 — Read the rules first
Before touching anything, we checked the bug bounty program's scope and confirmed the
one website we were **allowed** to test. It had extra rules too: tag every request with
a special label, and never flood the site with traffic. So everything below was done
with **single, careful, hand-typed requests** — never an automated hammering.

> 🧒 *Like: before exploring a house, you check which rooms you're allowed in, and you
> agree to knock once, not kick the door.*

### Step 1 — Look around the website
We used tools to list the store's web pages and hidden addresses (recon). We noticed
the store runs on a well-known shopping platform (**Salesforce Commerce Cloud**), which
told us roughly how it's built.

> 🧒 *Like: walking around a building and noticing "ah, this is a LEGO set — I know how
> LEGO fits together."*

### Step 2 — Chase a few dead ends (this is normal!)
We looked at several likely spots — an old file-fetching page, a login redirect, an
address-autocomplete box, the credit-card payment code. **Every one was a dead end**
for this kind of bug. Good hunting is mostly ruling things out. We wrote down *why*
each one didn't work and moved on fast.

> 🧒 *Like: checking under five rocks and finding nothing before the sixth has the bug
> under it.*

### Step 3 — Spot the interesting word
A parameter-discovery tool noticed the page mentioned a handler called
**`onvalidatemerchant`**. That's the exact Apple Pay handshake from section 3 — and
it's *famously* the spot where stores mess up the "check it's really Apple" step. Ears
perked up.

> 🧒 *Like: hearing a word you know means "treasure might be near."*

### Step 4 — Read the store's own instructions
Websites ship little instruction files (JavaScript) to your browser. We downloaded the
store's Apple Pay one and read it. It literally showed the store copying the web
address from the browser and forwarding it to its own back-end — **with no check that
it belonged to Apple.**

> 🧒 *Like: finding the receptionist's own notepad and reading "dial any number the
> guest gives me." Now we're pretty sure — but we still have to prove it really
> happens.*

### Step 5 — Set a trap and test it
This is the key move. We used a tool (`interactsh`) that gives us a **fresh web
address that only we can see visitors to**. Think of it as a **tripwire phone number**:
if anyone ever calls it, our tool tells us, with a full recording of the call.

Then we sent the store one polite request that said, in effect: *"Here's your Apple
validation address"* — but we wrote **our tripwire address** instead of Apple's.

Two things happened:

- The store replied to *us* with an **error** ("Unknown error"). Looks like it didn't
  work, right?
- But our **tripwire lit up.** The store's server had called our address — and in the
  message it sent, it included its **own private Apple Pay identity**. Caught red-handed.

> 🧒 *Like: you give the receptionist a note with YOUR phone number. They frown and say
> "that didn't work" to your face — but your phone is already ringing, and it's them,
> reading out the secrets.*

## 5. Wait — why was there an "error" if it worked?

This trips people up, so here's the simple version (the full diagram is in
[`docs/sequence-diagram.md`](./docs/sequence-diagram.md)):

The store called our tripwire *expecting* a proper Apple "yes, they're legit" ticket
back. We're not Apple, so we sent back plain junk. The store looked at our junk, said
"this isn't a valid Apple ticket," got confused, and showed *us* an error.

**But the damage was already done one step earlier** — it had already made the call and
already leaked its secret. The error is just the store tripping *after* it already
spilled the beans.

> 🧒 *The receptionist already read your secrets out loud. The fact that they hung up
> confused afterwards doesn't un-say them.*

## 6. Making sure it wasn't a fluke

One tripwire hit could be a coincidence (sometimes robots and scanners poke at
addresses). So we were strict about it:

- We didn't just get a "someone looked us up" ping — we got a **full message with the
  store's real secret inside**. Only the store itself could have written that.
- The message came from a **different kind of software** than our own tool — proof a
  *second, separate* machine (the store's server) made the call, not our own computer
  by accident.
- We **did the whole test again** with a brand-new tripwire address. Same result. Not a
  one-off.

> 🧒 *You didn't just hear a phone ring once. You heard it ring, recognized the secret
> being read, recognized it was the receptionist's voice not yours, and then you made
> it happen a second time on purpose.*

## 7. Being honest about the limits

We tried to see if we could push further — could this trick make the store call its own
*internal* private computers (which would be much worse)? We tested, but the store gave
the **same generic error** no matter what, so we couldn't tell. So in the report we
said plainly: *"confirmed it leaks the secret to the outside; could NOT confirm the
internal-network part."*

> 🧒 *If you're not sure, you say "I'm not sure" — you don't make it sound scarier than
> you proved. That's what makes people trust the rest of your report.*

## 8. The fix (it's small!)

The store just needs to add back the check Apple asked for:

> Before calling the address, confirm it actually ends in an official Apple domain. If
> it doesn't, refuse — **before making any call.**

You can watch this fix work in the demo: run `./demo/run_demo.sh --secure` and the
tripwire stays silent, because the store now refuses our fake address up front.

> 🧒 *Teach the receptionist: "only dial numbers on the official list." Problem solved.*

## 9. Why this matters (the impact)

- **Anyone** could do this — no login, no account, nothing. Just a visitor.
- It **leaked private configuration** the store never meant to show.
- SSRF bugs like this are often a *stepping stone* to worse things (reaching a company's
  internal systems), which is exactly why they're taken seriously even when the first
  leak looks small.

## 10. Tiny glossary

| Word | Kid-simple meaning |
|---|---|
| **SSRF** (Server-Side Request Forgery) | Tricking a server into making a request *for you*, to a place you picked. |
| **URL** | A web address, like `https://something.com/page`. |
| **`validationURL`** | The specific web address Apple Pay asks the store's server to call. The one we swapped. |
| **Out-of-band (OOB) / collaborator / interactsh** | Our "tripwire" address that tells us when someone secretly contacts it. |
| **Recon** | Looking around a target to map what's there before testing. |
| **Payload** | The specific thing we send to test the bug (here, our fake address). |
| **Merchant identifier** | The store's private Apple Pay "who I am" ID — the secret that leaked. |

---

### If you only remember three things
1. **The bug:** the store called any web address we handed it, no questions asked (SSRF).
2. **The proof:** it wasn't a guess — the store's server phoned *our* tripwire and read
   out its own secret, twice.
3. **The fix:** check the address is really Apple's before calling it.
