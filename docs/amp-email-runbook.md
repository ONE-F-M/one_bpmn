# AMP4Email Runbook — Sender Registration & Rollout

Audience: BPMN engine developers (dev allowlist) and Operations (production Google
sender registration). Covers the interactive AMP emails sent by `one_bpmn`'s
User Task notifications (`one_bpmn/email_builder/`).

## 1. Background

Gmail (and a few other providers) only render the interactive `text/x-amp-html`
MIME part for senders it trusts. There are two independent trust levels:

| Level | Who sees AMP rendering | How it's granted |
|---|---|---|
| **Dev allowlist** | Only the individual Gmail account that enabled it | Each developer flips a setting in *Gmail → Settings → Filters and Blocked Addresses → (hidden) Dynamic Email*, or via the AMP Playground / Gmail Developer Preview enrollment | Instant, per-mailbox, no Google review |
| **Production registration** | Every recipient, automatically | One-time sender registration submitted to Google via the official AMP-for-Email form | Requires Google review; SPF/DKIM/DMARC alignment + a passing AMP validator sample are prerequisites |

Until production registration is approved, **every** recipient outside the
dev allowlist sees the HTML fallback (`html_fallback.html`), not the AMP
version. This makes the fallback template a first-class deliverable, not a
degraded backup — see §5 for a known bug that currently breaks it.

## 2. Dev allowlist (do this first, before requesting anything from Google)

There are two separate ways to get a test AMP email into your own inbox —
use the Playground first, since it sidesteps your sending domain's
DKIM/SPF/DMARC setup entirely (see §5, item 4 for why that matters).

### 2a. AMP for Email Playground (fastest — no DKIM/domain setup needed)

1. Sign in to the Gmail account you want to test with.
2. Settings → See all settings → General → **Dynamic email** → click
   **Developer settings** → whitelist `amp@gmail.dev`. This is required —
   it's the actual address the Playground sends test emails from, and is
   a separate permission from enabling Dynamic Email itself.
3. Go to `https://playground.amp.dev/?runtime=amp4email` (confirm the
   format shown is **AMP for Email**, top-left).
4. Paste your AMP HTML (e.g. the `text/x-amp-html` part rendered by
   `render_amp()`) into the editor, replacing the default sample.
5. Use the Playground's send-test-email action, targeting your own
   address. Google's docs note the `From` and `To` must differ for this
   to work — the Playground handles that itself (sends from
   `amp@gmail.dev`).
6. Open it in Gmail — this exercises the *real* `action-xhr` endpoints
   (`handle_amp_action` / `submit_comment`) if the site is reachable
   (e.g. via a tunnel), since the email content is unchanged from what
   the app would actually send.

### 2b. Sending directly from the site (needed to test the full pipeline,
   including MIME injection and DKIM)

1. Send yourself a test email from a **local/dev site** using
   `bench --site <site> console`:
   ```python
   from one_bpmn.email_builder.composer import compose_and_send_task_email
   # or call render_amp() directly on a task_content dict and inspect the HTML
   ```
2. This requires an `Email Account` with `enable_outgoing=1` capable of
   actually delivering to the recipient, and — if testing Dynamic Email
   rendering rather than just MIME structure — the recipient's Gmail
   account needs **Dynamic email** enabled in Settings → General (this
   toggle alone does not bypass DKIM/SPF/DMARC requirements; see §5).
3. Open the email in Gmail web (not the mobile app — AMP rendering in
   Gmail mobile requires the same account-level toggle but behaves
   differently). Confirm the AMP buttons render instead of the plain
   HTML fallback.
6. If Gmail silently falls back to HTML, the most common causes are:
   - The email didn't pass AMP validation (see §4 — validate before
     debugging Gmail).
   - SPF/DKIM/DMARC don't align for the `From:` domain (see §3).
   - CORS preflight to `handle_amp_action` failed — check
     `templates/deployment/amp_cors_nginx.conf` is actually included in
     the site's nginx config and that `Access-Control-Allow-Origin`
     reflects `https://mail.google.com`.
7. If Gmail instead shows an explicit **"There was an error displaying
   your dynamic email (INTERNAL_ERROR)"** (rather than a silent HTML
   fallback), check DKIM *first*, before assuming it's a markup bug —
   confirmed on 2026-07-08 by sending a real test email from a Google
   Workspace mailbox (`s.shariff@one-fm.com`) on the `one-fm.com` domain
   with Dynamic Email already enabled and the AMP part independently
   validated as passing:
   - Open the email → click the **▼** next to the sender name (not the
     3-dot menu) → check for a **`signed-by:`** line. If it's missing
     (only `mailed-by:` shows), the message has **no DKIM signature at
     all** — Gmail's AMP4Email pipeline requires DKIM to pass before it
     will attempt to render dynamic content, and throws this internal
     error on unauthenticated mail rather than quietly falling back.
   - Root cause in our case: Google Workspace only DKIM-signs a custom
     domain (`one-fm.com`) if a Workspace admin has generated and turned
     on a DKIM key for it (Admin console → Apps → Google Workspace →
     Gmail → Authenticate email). An app password for an individual
     mailbox does not affect this — it's a domain-wide setting. If
     nobody has done this for `one-fm.com` (or for
     `notifications.one-fm.com` in production), every message from that
     domain goes out unsigned regardless of which app sends it.
   - To isolate "is it our code or the domain": repeat the same test
     using a plain `@gmail.com` address as both sender and recipient.
     Google always signs its own `gmail.com` domain, so if AMP renders
     there, the code path is confirmed working and the remaining issue
     is purely the sending domain's missing DKIM — a Workspace-admin
     fix, not a code fix.
   - **Caveat (2026-07-13):** the test above was sent via a local dev
     Email Account using a personal Gmail app password over
     `smtp.gmail.com` — a different sending path from production's real
     pipeline. A DNS check of `one-fm.com` (the real apex domain, not a
     `notifications.` subdomain — that was a misreading, see §8) shows
     SPF and DMARC already correctly configured, and a DKIM key already
     published at the default Google selector. Whether production mail
     is actually *signed* with it (vs. the key merely existing in DNS)
     was not conclusively established by the local test above — it
     could easily fail there even if production is fine, since they are
     different sending paths. §8 is the real, authoritative test.

## 3. Pre-flight checklist before requesting production registration

All of these must be true — Google's review will fail otherwise:

- [ ] **DKIM signing domain matches the `From:` domain.** Notifications
      are sent from `notifications@one-fm.com` — the domain is
      `one-fm.com` (not a `notifications.` subdomain — see §8). Verify
      with a real sent message using the procedure in §8, Step 1: the
      `d=` tag in the `DKIM-Signature` header of a received message must
      equal `one-fm.com`.
- [x] **SPF** — confirmed via `dig +short txt one-fm.com`:
      `v=spf1 include:_spf.google.com ~all`.
- [x] **DMARC** — confirmed via `dig +short txt _dmarc.one-fm.com`:
      `p=reject` (stricter than Google's minimum requirement of any
      policy at all), reports routed to `notifications@one-fm.com`.
- [x] **Every AMP sample submitted to Google passes the validator.**
      Run:
      ```
      bench --site <site> run-tests --app one_bpmn --module one_bpmn.tests.test_amp_validation
      ```
      (Requires `npx amphtml-validator` — see below.) Passing as of the
      fix in §5, item 1 (2026-07-07) — re-run before every submission,
      since any future template change can reintroduce a validation
      failure.
- [ ] **AMP CORS headers work in production**, not just locally —
      confirm `templates/deployment/amp_cors_nginx.conf` is deployed and
      `AMP-Access-Control-Allow-Source-Origin` is returned correctly by
      hitting `handle_amp_action` with an `AMP-Same-Origin` preflight.
- [ ] **Volume estimate ready** — Google's form asks for expected AMP
      email volume/day; get a rough number from Operations (count of
      User Tasks with `notifyAssignee=true` × average daily task
      creation).
- [ ] **Privacy policy URL** for one-fm.com ready (Google requires a
      link to the sending organization's privacy policy).

### Installing the AMP validator locally

```bash
npm install -g amphtml-validator
# or rely on npx (already supported by the test suite):
npx --yes amphtml-validator --html_format AMP4EMAIL path/to/file.html
```

## 4. Production Google sender registration (Operations — one-time)

**Important:** despite how this is sometimes phrased internally, Google
does **not** accept AMP-for-Email sender registration via email. It's a
web form review process:

1. Go to the official AMP for Email sender registration page:
   `https://amp.dev/documentation/guides-and-tutorials/email/register/`
   (verify this URL is still current before submitting — Google has moved
   AMP documentation pages before).
2. The form requires, at minimum:
   - Contact email (use an Operations-owned mailbox, not a personal one).
   - The sending domain(s) that will send AMP email —
     `notifications.one-fm.com`.
   - A sample AMP4EMAIL HTML document that **passes validation**. Use one
     of the golden samples in `one_bpmn/tests/fixtures/golden_amp_*.html`
     (regenerated via `one_bpmn/tests/_generate_golden_samples.py` — see
     §6; all three currently pass `test_amp_validation.py`).
   - Confirmation of SPF/DKIM/DMARC alignment (§3).
   - Expected send volume.
   - Privacy policy URL.
3. Submit and wait for Google's review (historically days to a few
   weeks — there is no SLA). Do not re-submit repeatedly; if rejected,
   Google's response usually states the specific reason.
4. Once approved, **no code change is required** on our side — Gmail
   begins rendering AMP for all recipients of mail from the registered
   domain automatically, as long as `frappe.flags.amp_html` continues to
   be set on qualifying sends.

## 5. Issues found and fixed (2026-07-07)

These were caught by actually running the test suite rather than trusting
its presence, and have been fixed:

1. **`amp_shell.html` rendered invalid AMP for link-only actions.**
   The AMP validator reported `form`/`template` tags used without their
   required extension scripts. Cause: `templates/emails/amp_shell.html`
   renders `<form>` (and the `submit-success`/`submit-error`
   `<template type="amp-mustache">` blocks inside it) whenever
   `has_actions and not is_comment`, but only included the
   `amp-form`/`amp-mustache` `<script>` tags when `has_token_actions or
   is_comment`. A User Task where every action requires confirmation or
   a digital signature (rendered as plain `<a>` links, no HMAC token —
   see `composer.py::_build_actions_for_email`) triggered this:
   `has_actions=True`, `has_token_actions=False`. **Fixed** by including
   the extension scripts whenever `has_actions or is_comment` (matching
   what the body actually renders).

2. **HTML fallback action buttons all linked to the same URL.**
   `templates/emails/html_fallback.html` rendered every action as
   `<a href="{{ open_link }}">` instead of `{{ action.url }}` — Approve
   and Reject buttons both opened the generic "Open in ERPNext" page.
   This affected every recipient until Google approves org-wide
   rendering (i.e., nearly everyone, initially). **Fixed** — now uses
   `{{ action.url or open_link }}`.

3. **`bench run-tests` did not run the unit-test suite.**
   `test_token.py`, `test_sanitizer.py`, `test_renderer.py`,
   `test_composer.py`, `test_amp_validation.py` used plain pytest
   classes instead of `FrappeTestCase`, so `bench run-tests --module
   <name>` reported "Ran 0 tests / OK" for each — a false pass.
   **Fixed** — all five converted to `FrappeTestCase`
   (`pytest.raises`/`pytest.mark.parametrize`/`pytest.skip` replaced
   with `assertRaises`/a `subTest` loop/`unittest.SkipTest`; autouse
   fixtures replaced with `setUp`/`addCleanup`). Two individual test
   bodies in `test_token.py` were also stale (didn't account for the
   base64url-encoded token payload) and have been corrected. All 44
   unit tests + 9 integration/regression tests (53 total) now pass under
   `bench run-tests`.

Golden AMP samples were regenerated after the template fix — see §6.

## 6. Regenerating golden AMP samples

After any template change, regenerate the committed golden fixtures used
by `TestGoldenSamples`:

```bash
python one_bpmn/tests/_generate_golden_samples.py
```

Re-run `test_amp_validation.py` afterward to confirm the regenerated
files still validate.

## 7. Adding AMP actions for a new doctype (plain Frappe Workflow)

Since 2026-07-08, `one_bpmn.api.workflow_actions.handle_workflow_action`
is a generic AMP action endpoint any doctype with a standard Frappe
Workflow can use — you do **not** need to write a new endpoint file. See
that module's docstring for the full config schema. Summary:

1. In your app's `hooks.py`, add an `amp_workflow_actions` entry (a flat
   **list** of dicts — not a nested dict, to avoid Frappe's hook-merge
   turning leaf values into single-item lists) naming the doctype,
   action, optional `from_state` idempotency guard, optional `fields`
   mapping (form-field-name → document-field-name; only these are ever
   written), optional `compute` (called before save), and optional
   `after` (called after the workflow transition commits).
2. Generate tokens with
   `one_bpmn.utils.token.generate_doc_action_token(doctype, docname, action, user)`
   and set `action_endpoint` in the rendered email's `task_content` to
   `{site_url}/api/method/one_bpmn.api.workflow_actions.handle_workflow_action`.
3. **Clear the hooks cache after registering** (`bench --site <site>
   clear-cache`, or restart the bench) — hooks are cached in Redis unless
   `developer_mode` is on, so a fresh `hooks.py` registration silently
   has no effect until the cache is cleared.
4. An unregistered (doctype, action) pair is rejected even with a
   validly-signed token for it — the registry is an allowlist, not just
   a lookup table, so this fails closed by design.

This was validated end-to-end (2026-07-08) with a temporary Leave
Application `Approve` / `Propose New Dates` registration — since removed,
as Leave Application is expected to become a real BPMN process, which
would use the standard `handle_amp_action` path instead. No doctype is
currently registered against this endpoint.

## 8. Final pre-submission verification & submission procedure (2026-07-13)

The AMP changes are deployed to production. This is the confirmed,
authoritative procedure for the two remaining manual steps before
Operations can submit the Google registration — both require production
access, which is outside what can be done from this dev environment.

**Note on the sending domain:** confirmed via DNS lookup that the real
domain is `one-fm.com` (e.g. `notifications@one-fm.com`), not a
`notifications.one-fm.com` subdomain — an earlier misreading in this
runbook. `one-fm.com` already has SPF and DMARC correctly configured and
a DKIM key published; whether it's actually signing production mail is
what step 1 below settles.

### Step 1 — DKIM verification (do this first)

1. Create a minimal BPMN process in production with a single User Task.
2. Configure its notification settings with `notifyAssignee = true` so
   the User Task assignment triggers the AMP email notification (see
   `one_bpmn.email_builder.composer.compose_and_send_task_email`).
3. Assign the User Task to an email address you can personally inspect —
   a Gmail account, or `s.shariff@one-fm.com` if you have full mailbox
   access there.
4. Publish the process in production and create a process instance. This
   triggers the BPMN email flow and sends the AMP notification from
   `notifications@one-fm.com` through the real production mail pipeline
   — not a local/dev shortcut.
5. Open the received email in Gmail → **Show original**. Confirm
   `DKIM: PASS` with `d=one-fm.com` (equivalently: the **▼** next to the
   sender name shows a `signed-by: one-fm.com` line).
6. **If it fails**, the remaining manual step is enabling authentication
   in Admin Console: **Apps → Google Workspace → Gmail → Authenticate
   email** for `one-fm.com` — then repeat this test.

Receiver-side note: the recipient inbox used in step 3 needs **Dynamic
email → Developer settings** enabled with `notifications@one-fm.com`
whitelisted, so it will actually attempt to render the AMP part rather
than silently showing the HTML fallback. This is a receiver-only
setting — there is no equivalent toggle needed on the sending side; the
sender's requirement is purely the DKIM/SPF/DMARC alignment being
verified here. It's also only needed for this pre-registration testing
phase — once Google approves the sender registration, rendering happens
automatically for every recipient, no toggle required anywhere.

### Step 2 — Google submission (only after step 1 passes)

1. Repeat the exact same process-instance trigger from Step 1, but this
   time assign/notify the User Task to
   `ampforemail.whitelisting@gmail.com` instead of a personal inbox.
   This must be a real, complete production send — not forwarded (Gmail
   strips the AMP MIME part on forward) and not a blank/placeholder
   email (Google rejects both).
2. Submit the **AMP for Email sender registration form** (§4), using
   this production email as the reference submission.
3. Wait for Google's review (~5 business days per their docs — no
   guaranteed SLA). Do not re-submit repeatedly.

**Do not skip ahead to Step 2 before Step 1 has actually passed** — a
submission sent while DKIM is unauthenticated will fail Google's review.
