# AMP email: sender registration

Gmail renders the interactive AMP part of an email only for senders Google has registered. Until then every recipient sees the HTML fallback. Registration is a one-time Operations task. Developer notes are in [`one_bpmn/processa_engine/notifications/README.md`](../one_bpmn/processa_engine/notifications/README.md).

The sending domain is `one-fm.com`; task emails come from `notifications@one-fm.com`.

## Before submitting

- [ ] **DKIM passes for `one-fm.com` on a real production email** (Step 1 below).
- [x] **SPF**: `dig +short txt one-fm.com` returns `v=spf1 include:_spf.google.com ~all`.
- [x] **DMARC**: `dig +short txt _dmarc.one-fm.com` returns a `p=reject` policy.
- [ ] **AMP validation passes** for the sample you submit (see the developer notes).
- [ ] **CORS works in production**: `one_bpmn/templates/deployment/amp_cors_nginx.conf` is deployed and `handle_amp_action` answers an `AMP-Same-Origin` preflight with `AMP-Access-Control-Allow-Source-Origin`.
- [ ] **Volume estimate**: User Tasks with `notifyAssignee=true` times average tasks per day.
- [ ] **Privacy policy URL** for one-fm.com.

## Step 1: check DKIM on a production email

1. In production, create a minimal process with one User Task that has `notifyAssignee = true`, assigned to a mailbox you can inspect.
2. The receiving Gmail account needs Dynamic email, Developer settings, with `notifications@one-fm.com` allowlisted. This is only needed until Google approves the sender.
3. Start an instance so the real production pipeline sends the email.
4. In Gmail, open Show original and confirm `DKIM: PASS` with `d=one-fm.com`.
5. If DKIM fails, a Google Workspace admin enables it for `one-fm.com` (Admin console, Apps, Google Workspace, Gmail, Authenticate email), then repeat.

## Step 2: submit to Google (only after Step 1 passes)

1. Trigger the same process again, with the User Task assigned to `ampforemail.whitelisting@gmail.com`. It must be a real, complete production send, not a forward (forwarding strips the AMP part).
2. Submit the AMP for Email sender registration form at `https://amp.dev/documentation/guides-and-tutorials/email/register/` (check the URL is still current). It asks for a contact mailbox owned by Operations, the sending domain `one-fm.com`, the sample, SPF, DKIM and DMARC alignment, expected volume and the privacy policy URL.
3. Wait for Google's review; there is no guaranteed time. Do not re-submit; a rejection states its reason.

Once approved, no code change is needed: Gmail renders the AMP part for every recipient.
