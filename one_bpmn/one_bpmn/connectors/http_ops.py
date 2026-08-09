# Copyright (c) 2026, one-fm and contributors
# The declarative HTTP executor — what makes a connector configurable rather
# than coded. An operation whose execution type is "HTTP Request" carries its
# URL, query, headers and body as Jinja templates on the BPMN Connector
# Operation row; this module renders them against the running instance, performs
# the request, and maps the response into the dict that lands in
# task.data[resultVariable].
#
# It is the same contract as a Python handler — ``execute(spec, params, ctx)``
# returns a JSON-safe dict — so dispatch_connector treats both identically.
#
# Safety: templates are authored by System Managers (the DocTypes are restricted
# to that role) and rendered with the same Jinja context connectorParams already
# used, so this adds no new expression surface. What it *does* add is outbound
# network reach, so the target host is checked before every call: https/http
# only, and private/loopback/link-local addresses are refused unless the
# connector explicitly sets Allow Internal Hosts.

import ipaddress
import json
import socket
from urllib.parse import urlencode, urlparse

import frappe

from one_bpmn.one_bpmn.integrations.retry import call_with_retry

# Response bodies beyond this are not parsed into task data — a workflow variable
# is not a file store, and an unbounded response would bloat every later save of
# the instance document.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Google access tokens last an hour; expire our cached copy early so one is never
# handed out with seconds left on it.
_TOKEN_TTL_SECONDS = 55 * 60


class ConnectorHTTPError(Exception):
    """A connector's HTTP call failed, or its configuration is unusable."""


def execute(spec, params, ctx):
    """Run one HTTP operation. ``spec`` comes from manifest.get_execution_spec."""
    render_ctx = _render_context(params, ctx)

    url = _build_url(spec, render_ctx)
    headers = _render_json_object(spec.headers_json, render_ctx, "Headers")
    query = _render_json_object(spec.query_params_json, render_ctx, "Query Parameters")
    body = _render_body(spec, render_ctx)

    _apply_auth(spec, headers, query)

    if query:
        url = f"{url}{'&' if urlparse(url).query else '?'}{urlencode(query)}"

    _assert_host_allowed(url, allow_internal=spec.allow_internal_hosts)

    response = _request(spec, url, headers, body)
    return _map_response(spec, response)


# ── Request ──────────────────────────────────────────────────────────────────
def _request(spec, url, headers, body):
    """Perform the call through Frappe's request helper, retrying 429/5xx."""
    import requests

    method = (spec.http_method or "POST").upper()
    kwargs = {"timeout": spec.request_timeout or 30}
    if headers:
        kwargs["headers"] = headers

    if method != "GET" and body is not None:
        if spec.body_content_type == "application/json":
            kwargs["json"] = body
        else:
            kwargs["data"] = body

    def _call():
        resp = requests.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp

    try:
        resp = call_with_retry(_call)
    except requests.HTTPError as e:
        detail = ""
        if e.response is not None:
            detail = (e.response.text or "")[:2000]
        raise ConnectorHTTPError(
            f"{method} {url} failed with HTTP {getattr(e.response, 'status_code', '?')}: {detail}"
        ) from e
    except requests.RequestException as e:
        raise ConnectorHTTPError(f"{method} {url} failed: {e}") from e

    return _parse_response(resp)


def _parse_response(resp):
    """Decode a response into JSON where possible, else text (size-capped)."""
    raw = resp.content or b""
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ConnectorHTTPError(
            f"Response is {len(raw)} bytes, above the {_MAX_RESPONSE_BYTES}-byte limit "
            "for connector output. Narrow the request or use a Python handler."
        )

    content_type = (resp.headers.get("Content-Type") or "").lower()
    text = raw.decode(resp.encoding or "utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            return {"text": text}
    return {"text": text, "statusCode": resp.status_code}


# ── Templating ───────────────────────────────────────────────────────────────
def _render_context(params, ctx):
    """The Jinja scope: the resolved field values plus the usual BPMN context."""
    return {
        "params": params,
        "doc": ctx.get("doc") or frappe._dict(),
        "instance": ctx.get("instance"),
        "task_data": ctx.get("task_data") or {},
        "frappe": frappe,
    }


# Frappe's Jinja environment renders an undefined reference as the literal debug
# text "{{ no such element: dict object['x'] }}" instead of raising. Left alone
# that string would be sent inside a URL, header or body — so an undefined
# reference is normalised to empty, matching how a missing ``doc`` field (None)
# already renders. Empty query/header values are then dropped by the caller.
_UNDEFINED_MARKER = "no such element:"


def _render(value, render_ctx, what):
    if not isinstance(value, str) or ("{{" not in value and "{%" not in value):
        return value
    try:
        rendered = frappe.render_template(value, render_ctx)
    except Exception as e:
        raise ConnectorHTTPError(f"{what} could not be rendered: {e}") from e

    if isinstance(rendered, str) and _UNDEFINED_MARKER in rendered:
        return _blank_undefined(rendered)
    return rendered


def _blank_undefined(rendered):
    """Replace each "{{ no such element: … }}" run with an empty string."""
    out = []
    rest = rendered
    while True:
        start = rest.find("{{")
        if start == -1:
            out.append(rest)
            break
        end = rest.find("}}", start)
        if end == -1:
            out.append(rest)
            break
        chunk = rest[start : end + 2]
        out.append(rest[:start])
        if _UNDEFINED_MARKER not in chunk:
            out.append(chunk)
        rest = rest[end + 2 :]
    return "".join(out)


def _build_url(spec, render_ctx):
    url = _render(spec.url_template, render_ctx, "URL Template")
    url = (url or "").strip()
    if not url:
        raise ConnectorHTTPError("The operation has no URL Template.")
    if url.lower().startswith(("http://", "https://")):
        return url
    if not spec.base_url:
        raise ConnectorHTTPError(
            f"URL {url!r} is relative but the connector has no Base URL."
        )
    return f"{spec.base_url}/{url.lstrip('/')}"


def _render_json_object(raw, render_ctx, what):
    """Render a JSON object's values, dropping empties. Returns a flat dict."""
    if not (raw or "").strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        raise ConnectorHTTPError(f"{what} is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ConnectorHTTPError(f"{what} must be a JSON object.")

    out = {}
    for key, value in parsed.items():
        rendered = _render(value, render_ctx, f"{what} → {key}")
        if rendered in (None, ""):
            continue
        out[str(key)] = rendered if isinstance(rendered, str) else json.dumps(rendered)
    return out


def _render_body(spec, render_ctx):
    """The request body: rendered, then JSON-parsed when the type says JSON."""
    raw = spec.body_template
    if not (raw or "").strip():
        return None

    rendered = _render(raw, render_ctx, "Body Template")
    if spec.body_content_type != "application/json":
        return rendered

    try:
        return json.loads(rendered)
    except ValueError as e:
        raise ConnectorHTTPError(
            f"Body Template did not render to valid JSON: {e}. "
            "Remember to quote Jinja values that must be strings."
        ) from e


# ── Auth ─────────────────────────────────────────────────────────────────────
def _apply_auth(spec, headers, query):
    """Attach the connector's credential to the outgoing request."""
    auth_type = spec.auth_type or "None"
    if auth_type == "None":
        return

    if auth_type == "Service Account JSON":
        headers["Authorization"] = f"Bearer {_service_account_token(spec)}"
        return

    secret = _read_secret(spec)
    if not secret:
        where = (
            f"{spec.auth_settings_doctype}.{spec.auth_secret_field}"
            if spec.credential_source == "From a settings DocType"
            else f"the Secret field on connector {spec.connector_id}"
        )
        raise ConnectorHTTPError(
            f"Auth Type {auth_type} is set but no secret was found at {where}."
        )

    if auth_type == "Bearer Token":
        headers["Authorization"] = f"Bearer {secret}"
    elif auth_type == "API Key Header":
        headers[spec.auth_header_name or "X-API-Key"] = secret
    elif auth_type == "API Key Query Param":
        query[spec.auth_query_param or "api_key"] = secret
    elif auth_type == "Basic":
        import base64

        # The secret holds "user:password"; encode it as the scheme requires.
        token = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"


def _service_account_token(spec):
    """Exchange a service-account key for an OAuth2 access token.

    This is what lets a Google connector be *configuration*. Every other auth
    type is a secret copied into a header; a service account is not — the key
    signs a JWT, Google exchanges it for a short-lived access token, and that
    token is the Bearer credential. Without this step the only way to call a
    Google API was a Python handler holding an SDK client, which is exactly the
    coupling this removes.

    Tokens are cached until shortly before they expire. A token lasts an hour
    and the exchange is a network round-trip and an RSA signature, so minting
    one per operation would add a second call to every single connector task.

    Scopes come from the connector's own configuration, so two connectors can
    use the same key with different scopes, or different keys entirely.
    """
    secret = _read_secret(spec)
    if not secret:
        where = (
            f"{spec.auth_settings_doctype}.{spec.auth_secret_field}"
            if spec.credential_source == "From a settings DocType"
            else f"the Secret field on connector {spec.connector_id}"
        )
        raise ConnectorHTTPError(
            f"Auth Type Service Account JSON is set but no key was found at {where}."
        )

    try:
        info = json.loads(secret) if isinstance(secret, str) else secret
    except ValueError as e:
        raise ConnectorHTTPError(
            f"The credential for connector {spec.connector_id} is not valid JSON — a "
            "service account key is the whole JSON file Google issued."
        ) from e

    scopes = [s.strip() for s in (getattr(spec, "auth_scopes", "") or "").split("\n") if s.strip()]
    if not scopes:
        raise ConnectorHTTPError(
            f"Connector {spec.connector_id} uses a service account but declares no Scopes. "
            "Google refuses a token request with no scope, so this must be set."
        )

    cache_key = f"bpmn_connector_sa_token:{spec.connector_id}"
    # expires=True matters. Without it a miss is written into frappe.local.cache
    # as None, while set_value(expires_in_sec=...) writes only to Redis — so the
    # next read in the same request finds the poisoned local None and re-mints.
    # The caching silently did nothing until this was passed.
    cached = frappe.cache().get_value(cache_key, expires=True)
    if cached:
        return cached

    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        creds.refresh(Request())
    except Exception as e:
        raise ConnectorHTTPError(
            f"Could not obtain a Google access token for {spec.connector_id}: {e}"
        ) from e

    # Expire our copy a minute early so a token never goes stale mid-request.
    frappe.cache().set_value(cache_key, creds.token, expires_in_sec=_TOKEN_TTL_SECONDS)
    return creds.token


def clear_service_account_token(connector_id):
    """Drop a cached access token — called when a connector's auth changes."""
    frappe.cache().delete_value(f"bpmn_connector_sa_token:{connector_id}")


def _read_secret(spec):
    """Decrypt the connector's credential at call time.

    Two sources, because both are legitimate:
      On this connector      — the Password field on BPMN Connector itself. The
                               default: one connector, one key, nothing else to set up.
      From a settings DocType — a Password field elsewhere, for a credential that
                               several connectors share (one service account behind
                               the four Google connectors), so rotating it is one edit.

    Read here rather than in get_execution_spec so a plaintext secret never sits
    in a spec that might be logged or cached.
    """
    if spec.credential_source == "From a settings DocType":
        if not (spec.auth_settings_doctype and spec.auth_secret_field):
            return None
        try:
            settings = frappe.get_single(spec.auth_settings_doctype)
            return settings.get_password(spec.auth_secret_field, raise_exception=False)
        except Exception:
            return None

    try:
        conn = frappe.get_doc("BPMN Connector", spec.connector_id)
        return conn.get_password("auth_secret", raise_exception=False)
    except Exception:
        return None


# ── Host allow-listing ───────────────────────────────────────────────────────
def _assert_host_allowed(url, allow_internal=False):
    """Refuse non-HTTP schemes, and internal addresses unless opted in.

    Without this a connector — which any System Manager can point anywhere —
    doubles as a request forger against the server's own network.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConnectorHTTPError(f"URL scheme {parsed.scheme!r} is not allowed (http/https only).")
    if not parsed.hostname:
        raise ConnectorHTTPError(f"URL {url!r} has no host.")
    if allow_internal:
        return

    for address in _resolve(parsed.hostname):
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ConnectorHTTPError(
                f"Host {parsed.hostname} resolves to the internal address {address}. "
                "Tick Allow Internal Hosts on the connector if that is intended."
            )


def _resolve(hostname):
    """Every IP a hostname resolves to (the literal itself if it is an IP)."""
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ConnectorHTTPError(f"Host {hostname} could not be resolved: {e}") from e

    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return out


# ── Response mapping ─────────────────────────────────────────────────────────
def _map_response(spec, response):
    """Project the response into the operation's declared output shape."""
    raw = (spec.response_map_json or "").strip()
    if not raw:
        return response if isinstance(response, dict) else {"response": response}

    try:
        mapping = json.loads(raw)
    except ValueError as e:
        raise ConnectorHTTPError(f"Response Map is not valid JSON: {e}") from e
    if not isinstance(mapping, dict):
        raise ConnectorHTTPError("Response Map must be a JSON object.")

    return {key: dig(response, path) for key, path in mapping.items()}


def dig(data, path):
    """Follow a dotted path into a response, e.g. ``files[0].id``. None if absent."""
    current = data
    for part in _path_parts(path):
        if isinstance(part, int):
            if not isinstance(current, (list, tuple)) or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current


def _path_parts(path):
    """``a.b[0].c`` → ["a", "b", 0, "c"]."""
    parts = []
    for chunk in str(path or "").split("."):
        name, _, rest = chunk.partition("[")
        if name:
            parts.append(name)
        while rest:
            index, _, rest = rest.partition("]")
            index = index.strip()
            if index.isdigit():
                parts.append(int(index))
            if rest.startswith("["):
                rest = rest[1:]
    return parts
