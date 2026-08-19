# Copyright (c) 2026, one-fm and contributors
# Authoring-side helpers for the Connector Agent.
#
# The agent that builds connectors is a BPMN map: its reasoning, its prompts and
# its routing all live in the Processa diagram, and its tool shapes are Server
# Scripts. Those scripts cannot import `requests`, open a socket or parse a spec
# on their own (see one_bpmn.security.script_validator), so everything mechanical
# lives here as an importable library the scripts call. Nothing in this module
# decides anything about *how the agent behaves* — that is the map's job.
#
# The division of labour is deliberate. An LLM is good at reading prose API
# documentation and naming things; it is bad at not inventing a field it then
# references in a URL template. So:
#
#   fetch_api_reference   — get the provider's docs/spec in (guarded)
#   summarize_openapi     — condense a spec to what fits in a prompt
#   openapi_to_manifest   — DETERMINISTIC draft: paths → operations → fields
#   validate_manifest     — DETERMINISTIC review of a draft, before it is written
#   try_operation         — one real call, so "it works" is observed, not claimed
#   write_draft_connector — write it DISABLED, so nothing goes live unreviewed
#
# The agent uses the LLM for the parts that need judgement (which endpoints
# matter, labels, help text, icon) and this module for the parts that must be
# right. That split is the whole reason a connector the agent writes can be
# trusted enough to hand to a person for one review.

import json
import re
from urllib.parse import urlparse

import frappe

from one_bpmn.one_bpmn.connectors import http_ops, manifest, validator

# An API reference page or spec is read into a prompt, so it is capped well below
# the connector response limit — a 2 MB HTML page is not a useful prompt and the
# tail of it is navigation furniture anyway.
_MAX_REFERENCE_BYTES = 512 * 1024

# How many operations a deterministic draft will emit from one spec. A large API
# (Stripe, Google) has hundreds of paths; a connector that lists all of them is
# unusable in the modeler dropdown and blows the prompt budget. The agent picks
# which ones matter and asks for those by name.
_MAX_DRAFT_OPERATIONS = 40

_VALID_FIELD_TYPES = {"String", "Text", "Dropdown", "Boolean", "Hidden"}
_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# OpenAPI security scheme → the connector's Auth Type enum. A scheme this map
# does not cover is reported rather than guessed: picking the wrong auth type
# produces a connector that fails at call time with a 401 and no clue why.
_AUTH_BY_SCHEME = {
    ("http", "bearer"): "Bearer Token",
    ("http", "basic"): "Basic",
    ("apikey", "header"): "API Key Header",
    ("apikey", "query"): "API Key Query Param",
    ("oauth2", None): "Bearer Token",
}


class ConnectorAuthoringError(frappe.ValidationError):
    pass


# ── Reading the provider's documentation ─────────────────────────────────────
def fetch_api_reference(url: str, max_bytes: int = _MAX_REFERENCE_BYTES) -> dict:
    """Fetch an API reference page or machine-readable spec.

    Same outbound posture as a connector call: http(s) only, and a host that
    resolves to a private/loopback/link-local address is refused. The agent is
    given a URL by whoever filed the work order, so this is a request forger
    unless it is guarded exactly like the executor is.

    Returns ``{url, kind, spec|text, truncated}`` where ``kind`` is "openapi"
    when the body parses as a spec with a ``paths`` object, else "text".
    """
    import requests

    url = (url or "").strip()
    if not url:
        raise ConnectorAuthoringError("No URL was given to read.")
    if not urlparse(url).scheme:
        url = "https://" + url

    # Reuses the executor's guard rather than reimplementing it, so the two can
    # never drift into disagreeing about what is safe to call.
    http_ops._assert_host_allowed(url, allow_internal=False)

    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"Accept": "application/json, application/yaml, text/html;q=0.8"},
            stream=True,
        )
        resp.raise_for_status()
        raw = resp.raw.read(max_bytes + 1, decode_content=True) or b""
    except requests.RequestException as e:
        raise ConnectorAuthoringError(f"Could not read {url}: {e}") from e

    truncated = len(raw) > max_bytes
    body = raw[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")

    spec = _parse_spec(body)
    if spec is not None:
        return {"url": url, "kind": "openapi", "spec": spec, "truncated": truncated}
    return {"url": url, "kind": "text", "text": _strip_markup(body), "truncated": truncated}


def _parse_spec(body: str):
    """Parse an OpenAPI/Swagger document out of a response body, or None."""
    text = (body or "").strip()
    if not text:
        return None

    parsed = None
    if text[0] in "{[":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    if parsed is None:
        try:
            import yaml

            parsed = yaml.safe_load(text)
        except Exception:
            return None

    if isinstance(parsed, dict) and isinstance(parsed.get("paths"), dict):
        return parsed
    return None


def _strip_markup(body: str) -> str:
    """HTML → readable text. A documentation page is mostly chrome; the prompt
    should carry the prose and the endpoint tables, not the navigation."""
    text = re.sub(r"(?is)<(script|style|nav|footer|svg)[^>]*>.*?</\1>", " ", body or "")
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"[ \t]*\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def summarize_openapi(spec: dict, max_operations: int = 120) -> dict:
    """Condense a spec into the shape a prompt can carry.

    A full spec is far too large to hand an LLM, and most of it is response
    schemas the connector never needs. What survives is what an operation row
    actually requires: method, path, summary, parameters and the request body's
    top-level properties.
    """
    if not isinstance(spec, dict):
        raise ConnectorAuthoringError("An OpenAPI summary needs the parsed spec object.")

    info = spec.get("info") or {}
    servers = [s.get("url") for s in (spec.get("servers") or []) if isinstance(s, dict)]
    if not servers and spec.get("host"):  # Swagger 2.0
        schemes = spec.get("schemes") or ["https"]
        servers = [f"{schemes[0]}://{spec['host']}{spec.get('basePath') or ''}"]

    operations = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.upper() not in _VALID_METHODS or not isinstance(op, dict):
                continue
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operationId": op.get("operationId"),
                    "summary": (op.get("summary") or op.get("description") or "")[:300],
                    "parameters": _summarize_parameters(spec, methods, op),
                    "body": _summarize_body(spec, op),
                }
            )
            if len(operations) >= max_operations:
                break
        if len(operations) >= max_operations:
            break

    return {
        "title": info.get("title"),
        "version": info.get("version"),
        "description": (info.get("description") or "")[:1000],
        "servers": servers,
        "security_schemes": _summarize_security(spec),
        "operations": operations,
        "operation_count_total": sum(
            1
            for m in (spec.get("paths") or {}).values()
            if isinstance(m, dict)
            for k in m
            if k.upper() in _VALID_METHODS
        ),
    }


def _summarize_parameters(spec: dict, path_item: dict, op: dict) -> list:
    """Path/query/header parameters, spec-level and operation-level merged."""
    out = []
    for raw in list(path_item.get("parameters") or []) + list(op.get("parameters") or []):
        p = _deref(spec, raw)
        if not isinstance(p, dict) or not p.get("name"):
            continue
        schema = _deref(spec, p.get("schema")) or {}
        out.append(
            {
                "name": p["name"],
                "in": p.get("in") or "query",
                "required": bool(p.get("required")),
                "type": schema.get("type") or p.get("type") or "string",
                "enum": schema.get("enum") or p.get("enum"),
                "description": (p.get("description") or "")[:200],
            }
        )
    return out


def _summarize_body(spec: dict, op: dict) -> dict | None:
    """Top-level properties of a JSON request body (one level deep only).

    Nested objects are named but not expanded: a connector field is a single
    input in a properties panel, so a deep structure is something the modeler
    supplies as a JSON blob, not something to flatten into forty fields.
    """
    body = _deref(spec, op.get("requestBody")) or {}
    content = body.get("content") or {}
    json_body = content.get("application/json") or content.get("*/*") or {}
    schema = _deref(spec, json_body.get("schema")) or {}

    if not schema and op.get("parameters"):  # Swagger 2.0 body parameter
        for raw in op["parameters"]:
            p = _deref(spec, raw) or {}
            if p.get("in") == "body":
                schema = _deref(spec, p.get("schema")) or {}
                break
    if not isinstance(schema, dict) or not schema.get("properties"):
        return None

    required = schema.get("required") or []
    props = {}
    for name, raw in (schema.get("properties") or {}).items():
        prop = _deref(spec, raw) or {}
        props[name] = {
            "type": prop.get("type") or "string",
            "required": name in required,
            "enum": prop.get("enum"),
            "description": (prop.get("description") or "")[:200],
        }
    return {"content_type": "application/json", "properties": props}


def _summarize_security(spec: dict) -> list:
    """Security schemes mapped onto the connector's Auth Type enum."""
    components = spec.get("components") or {}
    schemes = components.get("securitySchemes") or spec.get("securityDefinitions") or {}
    out = []
    for name, raw in (schemes or {}).items():
        s = _deref(spec, raw) or {}
        stype = (s.get("type") or "").lower()
        if stype == "http":
            key = (stype, (s.get("scheme") or "").lower())
        elif stype in ("apikey", "apiKey".lower()):
            key = ("apikey", (s.get("in") or "header").lower())
        else:
            key = (stype, None)
        out.append(
            {
                "name": name,
                "openapi_type": s.get("type"),
                "scheme": s.get("scheme"),
                "in": s.get("in"),
                "header_name": s.get("name") if (s.get("in") or "") == "header" else None,
                "query_param": s.get("name") if (s.get("in") or "") == "query" else None,
                "auth_type": _AUTH_BY_SCHEME.get(key),
            }
        )
    return out


def _deref(spec: dict, node):
    """Resolve a local ``$ref``. Remote refs are left alone — following one
    would be an unguarded outbound fetch from inside a parse."""
    seen = 0
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if not ref.startswith("#/") or seen > 10:
            return None
        target = spec
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return None
            target = target[part]
        node = target
        seen += 1
    return node


# ── Deterministic draft ──────────────────────────────────────────────────────
def openapi_to_manifest(
    spec: dict,
    connector_id: str,
    label: str = None,
    operations: list = None,
    base_url: str = None,
    source_url: str = None,
) -> dict:
    """Build a connector manifest from a spec, mechanically.

    ``operations`` selects which endpoints to include, as ``"METHOD /path"`` or
    an ``operationId``; without it the first few paths are taken, which is only
    useful for a small API. The agent is expected to choose.

    This is the Power-Platform/Airbyte move — path parameters become required
    fields, query parameters become optional ones, enums become dropdown
    choices, and the URL template is written to reference exactly the fields
    that were created. Nothing is invented, so nothing has to be checked for
    invention.
    """
    summary = summarize_openapi(spec, max_operations=1000)
    wanted = _select_operations(summary["operations"], operations)

    servers = summary.get("servers") or []
    resolved_base = (base_url or (servers[0] if servers else "") or "").rstrip("/")
    # A spec may declare a RELATIVE server url ("/api/v3" — the Swagger Petstore
    # does). Per OpenAPI that is relative to wherever the document was served, so
    # it is resolved against the URL it came from rather than shipped as-is: a
    # relative Base URL is a connector that cannot make a call.
    if resolved_base and not resolved_base.lower().startswith(("http://", "https://")):
        if source_url:
            from urllib.parse import urljoin

            resolved_base = urljoin(source_url, resolved_base).rstrip("/")
        else:
            raise ConnectorAuthoringError(
                f"The spec's server url {resolved_base!r} is relative and there is "
                "nothing to resolve it against. Pass the absolute base URL."
            )

    auth = {}
    for scheme in summary.get("security_schemes") or []:
        if scheme.get("auth_type"):
            auth = {
                "type": scheme["auth_type"],
                "source": "On this connector",
                "headerName": scheme.get("header_name"),
                "queryParam": scheme.get("query_param"),
            }
            break

    return {
        "connectorId": connector_id,
        "label": label or summary.get("title") or connector_id,
        "description": (summary.get("description") or "")[:500] or None,
        "api": {"name": summary.get("title"), "version": summary.get("version")},
        "execution": {
            "type": "HTTP Request",
            "baseUrl": resolved_base,
            "timeout": 30,
            "allowInternalHosts": False,
            "auth": {k: v for k, v in auth.items() if v} or {"type": "None"},
        },
        "operations": [_operation_from_spec(op, resolved_base) for op in wanted],
    }


def _select_operations(available: list, wanted: list) -> list:
    if not wanted:
        return available[:_MAX_DRAFT_OPERATIONS]

    index = {}
    for op in available:
        index[f"{op['method']} {op['path']}"] = op
        if op.get("operationId"):
            index[op["operationId"]] = op

    chosen, missing = [], []
    for key in wanted:
        op = index.get(str(key).strip())
        if op is None:
            missing.append(str(key))
        elif op not in chosen:
            chosen.append(op)
    if missing:
        raise ConnectorAuthoringError(
            "These operations are not in the spec: "
            + ", ".join(missing)
            + ". Use 'METHOD /path' exactly as the spec writes it, or an operationId."
        )
    return chosen[:_MAX_DRAFT_OPERATIONS]


def _operation_from_spec(op: dict, base_url: str) -> dict:
    """One spec operation → one manifest operation, fields included."""
    fields, url_template = [], op["path"]

    for p in op.get("parameters") or []:
        name = _field_name(p["name"])
        if p["in"] == "path":
            # The template must reference the field that carries the value, so
            # the two are generated together and cannot disagree.
            url_template = url_template.replace("{" + p["name"] + "}", "{{ params." + name + " }}")
            fields.append(_field(name, p, required=True))
        elif p["in"] in ("query", "header"):
            fields.append(_field(name, p, required=bool(p.get("required"))))

    query, headers = {}, {}
    for p in op.get("parameters") or []:
        name = _field_name(p["name"])
        if p["in"] == "query":
            query[p["name"]] = "{{ params." + name + " }}"
        elif p["in"] == "header":
            headers[p["name"]] = "{{ params." + name + " }}"

    body_template = None
    body = op.get("body")
    if body and op["method"] != "GET":
        pairs = []
        for prop_name, prop in (body.get("properties") or {}).items():
            name = _field_name(prop_name)
            fields.append(
                _field(
                    name,
                    {
                        "name": prop_name,
                        "type": prop.get("type"),
                        "enum": prop.get("enum"),
                        "description": prop.get("description"),
                    },
                    required=bool(prop.get("required")),
                )
            )
            pairs.append(f'"{prop_name}": "{{{{ params.{name} }}}}"')
        if pairs:
            body_template = "{" + ", ".join(pairs) + "}"

    operation_id = op.get("operationId") or _operation_id(op["method"], op["path"])
    # Key names are the importer's, not ours: seed._import_operation reads
    # op["method"] as the documentation string and everything executable out of
    # a nested op["http"] block (url/query/headers/contentType/body/responseMap).
    # Inventing a parallel spelling here is how a draft passes review and then
    # fails to import.
    http = {"method": op["method"], "url": url_template}
    if query:
        http["query"] = query
    if headers:
        http["headers"] = headers
    if body_template:
        http["contentType"] = "application/json"
        http["body"] = body_template

    return {
        "value": operation_id,
        "label": (op.get("summary") or operation_id)[:140],
        "description": op.get("summary") or None,
        "method": f"{op['method']} {op['path']}",
        "executionType": "HTTP Request",
        "http": http,
        "fields": _dedupe_fields(fields),
    }


def _field(name: str, p: dict, required: bool) -> dict:
    """A spec parameter/property → a modeler field row."""
    enum = p.get("enum") or []
    spec_type = (p.get("type") or "string").lower()
    if enum:
        field_type = "Dropdown"
    elif spec_type == "boolean":
        field_type = "Boolean"
    elif spec_type in ("object", "array"):
        field_type = "Text"
    else:
        field_type = "String"

    row = {
        "name": name,
        "label": _label(p.get("name") or name),
        "type": field_type,
        "required": bool(required),
        "expression": True,
    }
    if enum:
        row["choices"] = [{"label": _label(str(v)), "value": v} for v in enum]
    if p.get("description"):
        row["help"] = str(p["description"])[:500]
    return row


def _dedupe_fields(fields: list) -> list:
    """A path parameter and a body property can share a name; the row that
    already exists wins so the templates keep referring to one field."""
    seen, out = set(), []
    for f in fields:
        if f["name"] in seen:
            continue
        seen.add(f["name"])
        out.append(f)
    return out


def _field_name(raw: str) -> str:
    """A field name that is safe for both Jinja dot access and connectorParams.

    Anything that would shadow a dict method gets suffixed — ``params.values``
    silently resolves to the METHOD, which is the single most expensive mistake
    this configuration format allows (see validator._shadowed_field_access).
    """
    name = re.sub(r"[^0-9a-zA-Z_]", "_", str(raw or "")).strip("_") or "value"
    if name[0].isdigit():
        name = "f_" + name
    if hasattr({}, name):
        name = name + "_"
    return name


def _label(raw: str) -> str:
    text = re.sub(r"[_\-\.]+", " ", str(raw or "")).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return (text[:1].upper() + text[1:]) if text else ""


def _operation_id(method: str, path: str) -> str:
    parts = [p for p in re.split(r"[/{}]+", path) if p]
    tail = "".join(p[:1].upper() + p[1:] for p in parts[-2:])
    return (method.lower() + tail) or method.lower()


# ── Reviewing a draft before it is written ───────────────────────────────────
def validate_manifest(draft) -> list:
    """Structural review of a manifest dict — the gate before anything is saved.

    ``validator.validate_manifests`` only sees rows already in the database, so
    it cannot answer "is this draft safe to write". This does, and it checks the
    three things an LLM-authored connector actually gets wrong, none of which
    surface until a call is made:

      * a template referencing ``params.x`` for a field that was never declared
      * ``params.values`` / ``params.items`` — dot access resolving to the dict
        method rather than the field
      * a relative URL template with no Base URL behind it

    Returns human-readable issue strings; empty means the draft is well-formed.
    """
    if isinstance(draft, str):
        try:
            draft = json.loads(draft)
        except ValueError as e:
            return [f"the draft is not valid JSON: {e}"]
    if not isinstance(draft, dict):
        return ["a manifest must be a JSON object"]

    issues = []
    cid = (draft.get("connectorId") or "").strip()
    if not cid:
        issues.append("no connectorId")
    elif not re.match(r"^[a-z][a-z0-9_]*$", cid):
        issues.append(
            f"connectorId {cid!r} must start with a letter and use only lowercase "
            "letters, digits and underscores"
        )
    if not (draft.get("label") or "").strip():
        issues.append("no label")

    issues.extend(validator._validate_icon(cid or "?", draft.get("icon")))

    execution = draft.get("execution") or {}
    base_url = (execution.get("baseUrl") or "").strip()
    exec_type = execution.get("type") or "HTTP Request"
    if exec_type not in ("HTTP Request", "Python Handler"):
        issues.append(f"unknown execution type {exec_type!r}")
    if base_url and not base_url.lower().startswith(("http://", "https://")):
        issues.append(f"Base URL {base_url!r} must start with http:// or https://")

    # A credential the agent cannot see must still be *expected*, or the call
    # goes out unauthenticated and the provider answers 401.
    auth = execution.get("auth") or {}
    auth_type = auth.get("type") or "None"
    if auth_type not in (
        "None",
        "Bearer Token",
        "API Key Header",
        "API Key Query Param",
        "Basic",
        "Service Account JSON",
    ):
        issues.append(f"unknown auth type {auth_type!r}")
    if auth_type == "API Key Header" and not (auth.get("headerName") or "").strip():
        issues.append("Auth Type is API Key Header but no header name is set")
    if auth_type == "API Key Query Param" and not (auth.get("queryParam") or "").strip():
        issues.append("Auth Type is API Key Query Param but no query parameter name is set")
    if auth.get("secret") or auth.get("auth_secret"):
        # Belt and braces: a secret must reach the connector through a person,
        # never through a draft that is logged, prompted over and exported.
        issues.append("a manifest must not carry a secret value — only where the secret lives")

    operations = draft.get("operations")
    if not isinstance(operations, list) or not operations:
        issues.append(f"{cid or '?'}: no operations")
        return issues

    seen_ops = set()
    for op in operations:
        if not isinstance(op, dict):
            issues.append(f"{cid}: an operation is not an object")
            continue
        ov = (op.get("value") or "").strip()
        if not ov:
            issues.append(f"{cid}: operation missing 'value' (its id)")
            continue
        if ov in seen_ops:
            issues.append(f"{cid}: duplicate operation {ov!r}")
        seen_ops.add(ov)
        if not (op.get("label") or "").strip():
            issues.append(f"{cid}/{ov}: no label")

        fields = op.get("fields") or []
        issues.extend(validator._validate_fields(cid, ov, fields))
        issues.extend(_validate_operation_execution(cid, ov, op, fields, execution, base_url))

    return issues


def _validate_operation_execution(cid, ov, op, fields, connector_execution, base_url) -> list:
    """Executability + template↔field agreement for one drafted operation.

    Reads the SAME keys ``seed._import_operation`` reads. When these two
    disagree a draft passes review and then fails to import, which an agent
    experiences as a review that lies to it — it fixes a valid draft over and
    over until its tool budget runs out. That happened; hence this note.
    """
    issues = []
    http = op.get("http") or {}
    exec_type = op.get("executionType") or connector_execution.get("type") or "HTTP Request"

    if exec_type == "Python Handler":
        if not op.get("handlerPath"):
            issues.append(f"{cid}/{ov}: execution type is Python Handler but no handler path is set")
        return issues

    if not http:
        issues.append(
            f"{cid}/{ov}: no 'http' block — an HTTP operation needs "
            "http.method and http.url"
        )
        return issues

    method = (http.get("method") or "").upper()
    if not method:
        issues.append(f"{cid}/{ov}: no HTTP method (http.method)")
    elif method not in _VALID_METHODS:
        issues.append(f"{cid}/{ov}: unknown HTTP method {method!r}")

    url_template = (http.get("url") or "").strip()
    if not url_template:
        issues.append(f"{cid}/{ov}: no URL template (http.url)")
    elif not url_template.lower().startswith(("http://", "https://")):
        if not base_url and not url_template.startswith("{{"):
            issues.append(
                f"{cid}/{ov}: URL {url_template!r} is relative but the "
                "connector has no Base URL"
            )
        elif base_url and not url_template.startswith(("/", "{{")):
            issues.append(f"{cid}/{ov}: relative URL {url_template!r} should start with '/'")

    body_template = http.get("body")
    if method == "GET" and body_template:
        issues.append(f"{cid}/{ov}: a GET operation has a request body, which is not sent")
    # Query/header blocks are rendered with json.loads after templating, so a
    # malformed literal here fails every call rather than one.
    for key, label in (("query", "Query Parameters"), ("headers", "Headers")):
        raw = http.get(key)
        if raw in (None, "", {}):
            continue
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except ValueError as e:
                issues.append(f"{cid}/{ov}: {label} is not valid JSON ({e})")
                continue
        else:
            parsed = raw
        if not isinstance(parsed, dict):
            issues.append(f"{cid}/{ov}: {label} must be a JSON object")

    if body_template:
        issues.extend(_validate_body_template(cid, ov, body_template, http))

    issues.extend(_validate_response_map(cid, ov, http.get("responseMap")))
    issues.extend(_validate_template_fields(cid, ov, http, fields))
    return issues


def _validate_body_template(cid, ov, body_template, http) -> list:
    """A JSON body must still be JSON once the Jinja is substituted."""
    if (http.get("contentType") or "application/json") != "application/json":
        return []
    if not isinstance(body_template, str):
        # A dict body is dumped to JSON by the importer, so it cannot be
        # malformed — nothing to check.
        return []
    probe = re.sub(r"\{\{.*?\}\}", "1", str(body_template))
    probe = re.sub(r"\{%.*?%\}", "", probe)
    try:
        json.loads(probe)
    except ValueError as e:
        return [
            f"{cid}/{ov}: the JSON body template does not parse as JSON once the "
            f"expressions are filled in ({e})"
        ]
    return []


def _validate_response_map(cid, ov, response_map) -> list:
    if response_map in (None, "", {}):
        return []
    if isinstance(response_map, str):
        try:
            response_map = json.loads(response_map)
        except ValueError as e:
            return [f"{cid}/{ov}: Response Map is not valid JSON ({e})"]
    if not isinstance(response_map, dict):
        return [f"{cid}/{ov}: Response Map must be a JSON object of name → dotted path"]

    issues = []
    for out_name, path in response_map.items():
        if not isinstance(path, str) or not path.strip():
            issues.append(f"{cid}/{ov}: Response Map entry {out_name!r} has no path")
        elif not re.match(r"^[A-Za-z0-9_]+(\[\d+\])?(\.[A-Za-z0-9_]+(\[\d+\])?)*$", path.strip()):
            issues.append(
                f"{cid}/{ov}: Response Map path {path!r} is not a dotted path "
                "(use data.items[0].label)"
            )
    return issues


def _validate_template_fields(cid, ov, http, fields) -> list:
    """Every ``params.x`` in a template must be a field that exists.

    This is the check that earns its keep. An LLM writes a URL template
    referencing ``params.ticket_id`` and declares a field called ``ticket``;
    nothing complains until the call goes out with the literal debug text or a
    blank in the path.
    """
    declared = {f.get("name") for f in fields if isinstance(f, dict) and f.get("name")}
    blob = " ".join(
        json.dumps(http.get(key)) if not isinstance(http.get(key), str) else http[key]
        for key in ("url", "query", "headers", "body")
        if http.get(key)
    )

    issues = []
    referenced = set(re.findall(r"params\.([A-Za-z_][A-Za-z0-9_]*)", blob))

    # Shadowing is checked across EVERY referenced name, declared or not. A field
    # that is properly declared as `values` and read as `params.values` is the
    # dangerous case — the template silently renders the dict method and the
    # provider rejects the call for an unrelated-looking reason.
    for name in sorted(n for n in referenced if hasattr({}, n)):
        issues.append(
            f'{cid}/{ov}: template uses params.{name} — that resolves to the dict '
            f'method, not a field. Rename the field or use params["{name}"].'
        )
    for name in sorted(referenced - declared):
        if not hasattr({}, name):
            issues.append(
                f"{cid}/{ov}: template references params.{name} but no field named "
                f"{name!r} is declared"
            )
    for name in sorted(declared - referenced):
        bracket = f'params["{name}"]' in blob or f"params['{name}']" in blob
        if not bracket:
            issues.append(
                f"{cid}/{ov}: field {name!r} is declared but no template uses it — "
                "the modeler would fill in a value that goes nowhere"
            )

    # The None-literal trap: an unset doc/task_data value renders as the string
    # "None" rather than empty, which reaches the provider verbatim.
    for expr in re.findall(r"\{\{\s*((?:doc|task_data)\.[A-Za-z0-9_\.]+)\s*\}\}", blob):
        issues.append(
            f"{cid}/{ov}: {{{{ {expr} }}}} renders the literal 'None' when unset — "
            f'write {{{{ {expr} or "" }}}}'
        )
    return issues


# ── Trying it for real ───────────────────────────────────────────────────────
def try_operation(connector_id: str, operation: str, params=None, allow_disabled: bool = True) -> dict:
    """Run ONE operation once, with given inputs, and report what happened.

    This is the step that makes an agent-authored connector trustworthy: the
    difference between "the configuration looks right" and "the provider
    answered". It goes through the same ``http_ops.execute`` a real dispatch
    uses — same auth, same host guard, same size cap — so a pass here means the
    live path works, not that a parallel test path does.

    ``allow_disabled`` exists because the agent writes connectors DISABLED: the
    whole point is to test before a person enables it, and dispatch's own spec
    lookup refuses a disabled connector.
    """
    if isinstance(params, str):
        try:
            params = json.loads(params or "{}")
        except ValueError as e:
            raise ConnectorAuthoringError(f"Test inputs are not valid JSON: {e}") from e
    params = params or {}
    if not isinstance(params, dict):
        raise ConnectorAuthoringError("Test inputs must be a JSON object of field name → value.")

    spec = manifest.get_execution_spec(connector_id, operation, allow_disabled=allow_disabled)
    if not spec:
        raise ConnectorAuthoringError(
            f"No enabled operation {operation!r} on connector {connector_id!r} — "
            "check the operation id, and that the operation row is enabled."
        )
    if spec.execution_type != "HTTP Request" or spec.handler_path:
        raise ConnectorAuthoringError(
            "Only an HTTP Request operation can be test-called from here; a Python "
            "Handler operation runs provider code and must be tested in a diagram."
        )

    # field_specs() goes through the cached manifest projection, which EXCLUDES
    # disabled connectors — so for the case this function exists for (a draft the
    # agent just wrote, still disabled) it returns nothing and the required-field
    # check silently passes. Read the disabled-inclusive projection instead.
    fields = {}
    for m in manifest.load_manifests(include_disabled=True):
        if m.get("connectorId") != connector_id:
            continue
        for op in m.get("operations") or []:
            if op.get("value") == operation:
                fields = {f["name"]: f for f in op.get("fields") or [] if f.get("name")}
    missing = [
        name
        for name, field in fields.items()
        if field.get("required") and params.get(name) in (None, "")
    ]
    if missing:
        raise ConnectorAuthoringError(
            "These required fields have no test value: " + ", ".join(sorted(missing))
        )

    # ctx mirrors a dispatch with no process behind it: templates that reach for
    # doc/task_data/instance get empty containers rather than an AttributeError,
    # so a test failure is about the request, not about the harness.
    ctx = {"instance": None, "task": None, "doc": None, "task_data": {}}
    try:
        output = http_ops.execute(spec, params, ctx)
    except Exception as e:
        return {
            "ok": False,
            "connector": connector_id,
            "operation": operation,
            "error": str(e)[:2000],
            "error_type": type(e).__name__,
        }
    return {
        "ok": True,
        "connector": connector_id,
        "operation": operation,
        "output": output,
        "output_keys": sorted(output.keys()) if isinstance(output, dict) else None,
    }


# ── Writing it, disabled ─────────────────────────────────────────────────────
def write_draft_connector(draft, overwrite: bool = False) -> dict:
    """Validate, then write a draft as a DISABLED connector.

    Disabled is the whole safety story of an agent that authors connectors: the
    rows are real (so a person can read, test and fix them in the desk) but the
    modeler will not offer the connector and dispatch refuses it, so nothing an
    agent wrote can be called from a diagram until a human enables it. The
    secret is never part of the draft, so enabling is also the moment a person
    has to supply the credential — the review is structurally unavoidable rather
    than merely recommended.
    """
    if isinstance(draft, str):
        draft = json.loads(draft)

    issues = validate_manifest(draft)
    if issues:
        return {"written": False, "issues": issues}

    from one_bpmn.one_bpmn.connectors.seed import import_manifest

    cid = draft["connectorId"]
    existed = bool(frappe.db.exists("BPMN Connector", cid))
    if existed and not overwrite:
        return {
            "written": False,
            "issues": [
                f"connector {cid!r} already exists — pass overwrite to replace its "
                "operations, or choose another connectorId"
            ],
        }

    # The importer has validation of its own. If it ever refuses a draft this
    # module approved, that disagreement is reported as an ISSUE rather than
    # raised: an agent told "approved" and then handed an exception has nothing
    # to act on and will re-draft a valid connector until its budget runs out.
    try:
        state = import_manifest(draft, overwrite=True)
    except Exception as e:
        frappe.db.rollback()
        return {
            "written": False,
            "issues": [
                f"the importer refused this draft: {e}. This is a disagreement "
                "between the reviewer and the importer, not something you can fix "
                "by redrafting — report it and stop."
            ],
        }

    # import_manifest sets enabled=1 (it is also the shipped-seed path). An
    # agent-authored connector must not be callable yet, so it is unticked
    # straight after, before the cache is rebuilt.
    frappe.db.set_value("BPMN Connector", cid, "enabled", 0, update_modified=True)
    manifest.clear_manifest_cache()

    return {
        "written": True,
        "connector": cid,
        "state": state,
        "enabled": False,
        "operations": [op.get("value") for op in draft.get("operations") or []],
        "next_step": (
            f"Open BPMN Connector {cid}, paste the credential into Secret, run "
            "Validate Configuration, then tick Enabled."
        ),
    }
