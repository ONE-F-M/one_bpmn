# notifications: AMP and HTML task emails

Developer notes for the interactive emails one_bpmn sends. Sender registration with Google and the DKIM check are operations work: see [`docs/amp-email-operations.md`](../../../docs/amp-email-operations.md).

## What sends what

- `composer.compose_and_send_task_email`: the User Task email, sent when a task with `notifyAssignee=true` opens. It renders an AMP part and an HTML fallback, with one-click action buttons carrying HMAC tokens.
- `composer.compose_and_send_info_email`: renders the AMP info card for a Send Email service task (no action buttons); `dispatch_email` sends it.
- Both send through `composer.send_email`, which calls `frappe.sendmail` with the `bpmn_email` template and sets `frappe.flags.amp_html`.
- The `text/x-amp-html` part is added by an Email Queue `after_insert` hook that lives in one_fm (`one_fm/events/email_queue.py`), not in this app. On a site without one_fm, only the HTML part is sent.

The sender is the Email Account named on the task (`notifyAssigneeAccount` or `emailAccount`), else the site's default outgoing account.

## Files

- `renderer.py`: `render_amp`, `render_html_fallback` and the layout renderers.
- `actions.py`: adds HMAC tokens to the actions, and the logic behind the email callbacks (CORS headers, reasons, receipts, the conversation thread).
- `token.py`: makes and checks the HMAC tokens; every generator seals its payload with `_seal`.
- `comment_fields.py`: the Custom Fields on Comment.
- `fields.py`: the fact and detail rows shown in a card.
- `sanitizer.py`: cleans HTML for the AMP part.
- Templates: `one_bpmn/templates/emails/` (`amp_shell.html`, `html_fallback.html`, `layout_shell.html`, `layout_fallback.html`, `layouts/`, `partials/`).

Until Google approves the sender, every recipient outside the developer allowlist sees the HTML fallback, so treat the fallback as a deliverable in its own right.

## Endpoints the AMP part calls

- `one_bpmn.api.email_actions.handle_amp_action`: completes a BPMN task from a button.
- `one_bpmn.api.email_actions.submit_comment`: posts a comment.
- `one_bpmn.api.workflow_actions.handle_workflow_action`: applies a plain Frappe Workflow action (below).

Gmail's AMP requests carry no Frappe session; the signed token is the only trust anchor. CORS for these requests is set by `one_bpmn/templates/deployment/amp_cors_nginx.conf`, which must be included in the site's nginx config, with `Access-Control-Allow-Origin` reflecting `https://mail.google.com`.

## Validating AMP

Every template change must still pass the AMP validator:

```bash
npm install -g amphtml-validator
bench --site <site> run-tests --app one_bpmn --module one_bpmn.tests.test_amp_validation
```

The tests also run the validator through `npx amphtml-validator` when it is not installed globally.

After a template change, regenerate the golden samples and re-run the validation tests:

```bash
python one_bpmn/tests/_generate_golden_samples.py
```

The samples are `one_bpmn/tests/fixtures/golden_amp_action.html`, `golden_amp_comment.html` and `golden_amp_info.html`.

## Testing in your own Gmail

1. **AMP Playground (no domain setup).** In Gmail: Settings, General, Dynamic email, Developer settings, and allowlist `amp@gmail.dev`. Paste the output of `render_amp()` into `https://playground.amp.dev/?runtime=amp4email` and send a test email to yourself. The buttons call the real endpoints if your site is reachable.
2. **From a dev site (tests MIME and DKIM).** Send with `compose_and_send_task_email` from `bench --site <site> console`, using an Email Account with outgoing enabled. The recipient needs Dynamic email turned on, and the message needs passing DKIM.

If Gmail shows the HTML fallback, check in this order: the AMP validator, SPF, DKIM and DMARC alignment of the From domain, then the CORS preflight. If Gmail shows "There was an error displaying your dynamic email (INTERNAL_ERROR)", check DKIM first: open the message, and the sender details must show a `signed-by:` line. To tell a code problem from a domain problem, send the same email between two `@gmail.com` addresses, which Google always signs.

## AMP actions for any DocType with a Frappe Workflow

`handle_workflow_action` serves any DocType that uses a standard Frappe Workflow; its module docstring has the full schema.

1. In the owning app's `hooks.py`, add an `amp_workflow_actions` entry: a flat list of dicts naming `doctype`, `action`, and optionally `from_state`, `fields` (form field to document field; only these are written), `required_fields`, `compute` (runs before save) and `after` (runs after the transition commits).
2. Make tokens with `one_bpmn.processa_engine.notifications.token.generate_doc_action_token(doctype, docname, action, user)` and point the email's `action_endpoint` at `/api/method/one_bpmn.api.workflow_actions.handle_workflow_action`.
3. Clear the cache (`bench --site <site> clear-cache`) after registering; hooks are cached unless `developer_mode` is on.

An unregistered DocType and action pair is refused even with a valid token. No DocType is registered today.
