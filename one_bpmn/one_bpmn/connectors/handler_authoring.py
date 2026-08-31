# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Author a connector's Python handler and deliver it as a pull request.

WHY A CONNECTOR SOMETIMES NEEDS PYTHON
--------------------------------------
An operation says how it runs: ``execution_type`` is either "HTTP Request" — the
declarative executor, no code — or "Python Handler", a dotted ``handler_path``
the dispatcher resolves with ``frappe.get_attr``. Most REST APIs need no code at
all, which is the whole point of connectors-as-configuration. Some do: a
signed-request scheme, pagination that has to be walked, a multi-call sequence, a
response that needs reshaping beyond a dotted path.

The Connector Agent could already build the first kind and not the second. This
module is the second kind, and it exists because a handler is *real application
code* — it cannot be a Server Script (the BPMN script gate forbids ``requests``,
which is the one thing a handler is for) and it must not be written straight into
a running site. So it travels the way schema customizations already travel: as a
pull request a person reviews and merges.

THE SHAPE OF WHAT IS GENERATED
------------------------------
One module per connector, at
``one_bpmn/one_bpmn/connectors/generated/<connector_id>_ops.py``, holding one
function per operation with the dispatcher's contract:

    def operation_name(params: dict, ctx: dict) -> dict

``params`` arrives already Jinja-rendered with value transforms applied;
whatever the function returns lands in the task's output variable. A second
operation on the same connector appends to the same module rather than starting a
new one — see ``merge_module``.

WHAT IS AND IS NOT CHECKED
--------------------------
``screen_code`` is a deliberately narrow malicious-construct check: no ``eval``,
no ``exec``, no ``subprocess``, no dunder/frame reflection, no
``ignore_permissions``, no shell-out or destructive filesystem calls. It does NOT
attempt to judge whether the handler is *correct*, and it deliberately permits
``requests`` and the rest of the outbound-call toolkit — a screen that banned
those would ban every handler worth writing. Correctness is the reviewer's job,
which is why this ships a PR instead of a deployment.
"""

from __future__ import annotations

import ast
import re

import frappe
from frappe import _

# The generated module's location is derived from the configured app rather than
# fixed, so a different Connector Handler App gets a file path and a dotted module
# that agree with each other — see ``_connectors_home``.

# The dispatcher calls every handler this way; see
# ``dispatchers._resolve_connector_handler``.
HANDLER_ARGS = ("params", "ctx")

# The app whose repository receives the pull request, when Processa Settings does
# not say. Connectors live here, so their handlers do too — a handler in the
# customization app would be code in one repository reaching into a contract
# defined in another. The setting exists because the connector layer could be
# forked, vendored or moved, and none of those should need a code change.
DEFAULT_HANDLER_APP = "one_bpmn"


def handler_app() -> str:
    """The app whose repository receives handler pull requests, or "".

    Blank is a deliberate answer, not a misconfiguration: it turns handler
    authoring off on a site that does not want an agent proposing code. Callers
    report that as a refusal rather than silently falling back, because falling
    back would push code at a repository nobody nominated.
    """
    try:
        configured = frappe.db.get_single_value("Processa Settings", "connector_handler_app")
    except Exception:
        # The field is not installed yet (its patch has not run). Treat that as
        # unset rather than failing — the caller's message says what to do.
        return DEFAULT_HANDLER_APP
    if configured is None:
        return DEFAULT_HANDLER_APP
    return (configured or "").strip()

# ── the malicious-construct screen ───────────────────────────────────────────
# Modules that have no business in a connector handler. `requests`, `json`, `re`,
# `datetime`, `base64`, `hashlib`, `hmac`, `urllib.parse`, `time` and `frappe`
# are all deliberately absent from this list.
_BANNED_MODULES = {
    "subprocess", "ctypes", "pickle", "marshal", "shelve", "importlib",
    "builtins", "__builtin__", "pty", "socketserver", "multiprocessing",
}

# Builtins that turn a reviewed function into an arbitrary-code loader.
_BANNED_NAMES = {
    "eval", "exec", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "memoryview",
}

# Dotted calls that shell out or destroy data.
_BANNED_CALLS = {
    "os.system", "os.popen", "os.execv", "os.execve", "os.fork", "os.kill",
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.truncate",
    "shutil.rmtree", "shutil.move", "sys.exit",
}


def is_permanent_delivery_failure(error) -> bool:
    """Would retrying this delivery fail identically?

    A rejected or absent credential will be rejected again, and so will an
    unconfigured repository. Saying so matters because the caller is a model with
    a tool budget: observed live, it retried a 401 four times before giving up,
    spending four turns to learn what the first answer already said.
    """
    blob = f"{error}".lower()
    return any(k in blob for k in ("401", "403", "bad credentials", "not configured"))


def _dotted(node) -> str:
    """The dotted source text of an attribute/name chain, or ""."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def screen_code(code: str) -> list[str]:
    """Malicious constructs in ``code``, as a list of human-readable findings.

    Empty list means nothing objectionable was found — NOT that the code is
    correct. See the module docstring.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [_("The code does not parse: {0}").format(exc)]

    findings = []
    for node in ast.walk(tree):
        # import subprocess / from subprocess import ...
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root in _BANNED_MODULES:
                    findings.append(_("imports '{0}'").format(alias.name))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BANNED_MODULES:
                findings.append(_("imports from '{0}'").format(node.module))

        # eval(...), getattr(...), and friends
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            findings.append(_("uses '{0}'").format(node.id))

        # os.system(...), shutil.rmtree(...)
        elif isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted in _BANNED_CALLS:
                findings.append(_("calls '{0}'").format(dotted))
            # __globals__, __class__, __subclasses__ — frame and type reflection
            elif node.attr.startswith("__") and node.attr.endswith("__"):
                findings.append(_("reaches a dunder attribute '{0}'").format(node.attr))

        # ignore_permissions=True, anywhere
        elif isinstance(node, ast.keyword) and node.arg == "ignore_permissions":
            findings.append(_("passes ignore_permissions"))

    # Deduplicate but keep the order they were found in.
    seen, ordered = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered


# ── naming ───────────────────────────────────────────────────────────────────
def module_basename(connector_id: str) -> str:
    return f"{frappe.scrub(connector_id)}_ops.py"


def _connectors_home(app: str) -> tuple[str, str]:
    """Where ``connectors/`` lives in ``app``: (repo-relative dir, dotted prefix).

    Apps differ in how deeply they nest. one_bpmn puts a module directory of the
    same name inside its package, so its connectors sit at
    ``one_bpmn/one_bpmn/connectors`` and import as
    ``one_bpmn.one_bpmn.connectors``; a flatter app would have one level fewer.
    Rather than assume, look for the directory that is actually there — the file
    path and the dotted module MUST agree or the handler is written somewhere it
    can never be imported from.
    """
    import os

    app_path = frappe.get_app_path(app)             # …/apps/<app>/<package>
    repo_root = os.path.dirname(app_path)           # …/apps/<app>
    package = os.path.basename(app_path)

    # Candidates in the order they are preferred: the nested layout one_bpmn uses,
    # then the flat one.
    for parts in ((package, "connectors"), ("connectors",)):
        if os.path.isdir(os.path.join(app_path, *parts)):
            rel = "/".join((package,) + parts)
            dotted = ".".join((package,) + parts)
            return rel, dotted

    # Nothing there yet — create it in the nested position when the app nests,
    # otherwise flat. Derived the same way so the two halves still agree.
    if os.path.isdir(os.path.join(app_path, package)):
        return f"{package}/{package}/connectors", f"{package}.{package}.connectors"
    return f"{package}/connectors", f"{package}.connectors"


def repo_path(connector_id: str, app: str | None = None) -> str:
    """Repository-relative path of a connector's generated module."""
    rel, _dotted = _connectors_home(app or handler_app() or DEFAULT_HANDLER_APP)
    return f"{rel}/generated/{module_basename(connector_id)}"


def dotted_module(connector_id: str, app: str | None = None) -> str:
    _rel, dotted = _connectors_home(app or handler_app() or DEFAULT_HANDLER_APP)
    return f"{dotted}.generated.{frappe.scrub(connector_id)}_ops"


def handler_path(connector_id: str, function_name: str, app: str | None = None) -> str:
    """The value that goes in BPMN Connector Operation.handler_path."""
    return f"{dotted_module(connector_id, app)}.{function_name}"


# ── validation ───────────────────────────────────────────────────────────────
def validate_handler(code: str, function_name: str) -> dict:
    """Is ``code`` a usable handler defining ``function_name``?

    Returns ``{"ok": bool, "errors": [...], "warnings": [...]}``. Never raises,
    so a caller can report every problem in one reply instead of one per turn.
    """
    errors, warnings = [], []

    if not (code or "").strip():
        return {"ok": False, "errors": [_("No code was supplied.")], "warnings": []}
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", function_name or ""):
        errors.append(
            _("'{0}' is not a usable function name (lower_snake_case, no leading digit).")
            .format(function_name)
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False, "errors": [_("The code does not parse: {0}").format(exc)], "warnings": []}

    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    target = functions.get(function_name)
    if target is None:
        errors.append(
            _("The code defines {0} but not '{1}'.").format(
                ", ".join(sorted(functions)) or _("no top-level function"), function_name
            )
        )
    else:
        if isinstance(target, ast.AsyncFunctionDef):
            errors.append(_("'{0}' is async; the dispatcher calls handlers synchronously.").format(function_name))
        args = [a.arg for a in target.args.args]
        if tuple(args[:2]) != HANDLER_ARGS:
            errors.append(
                _("'{0}' must take exactly ({1}); it takes ({2}).").format(
                    function_name, ", ".join(HANDLER_ARGS), ", ".join(args) or _("nothing")
                )
            )
        returns = [n for n in ast.walk(target) if isinstance(n, ast.Return) and n.value is not None]
        if not returns:
            warnings.append(
                _("'{0}' never returns a value, so the task's output variable will be empty.")
                .format(function_name)
            )

    findings = screen_code(code)
    errors.extend(_("Not allowed in a handler: it {0}.").format(f) for f in findings)

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ── module rendering ─────────────────────────────────────────────────────────
_MODULE_HEADER = '''"""
Python handlers for the "{label}" connector.

Generated by the Connector Agent and delivered as a pull request, then resolved
at run time through each operation's ``handler_path``. Every function takes the
resolved ``params`` dict and the dispatch ``ctx``, and returns the dict that
becomes the service task's output variable.

Edit freely — this file is ordinary application code. A later proposal for the
same connector replaces only the function it names and leaves the rest alone.
"""
'''


def render_module(connector_id: str, label: str, functions: list[str]) -> str:
    """A whole generated module from its header and function sources."""
    body = "\n\n".join(f.strip("\n") for f in functions if (f or "").strip())
    return _MODULE_HEADER.format(label=label or connector_id) + "\n\n" + body + "\n"


def merge_module(existing: str | None, connector_id: str, label: str,
                 function_name: str, code: str) -> str:
    """Add or replace one function in a connector's generated module.

    ``existing`` is the module's current text on the target branch, or None when
    the connector has no module yet. A proposal for a function that is already
    there REPLACES it — a connector's operation is authored once and then
    corrected, and two functions of the same name in one module would mean the
    handler that runs depends on file order.
    """
    new_fn = code.strip("\n")
    if not (existing or "").strip():
        return render_module(connector_id, label, [new_fn])

    tree = ast.parse(existing)
    lines = existing.splitlines(keepends=True)
    kept = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == function_name:
            continue  # the one being replaced
        start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
        kept.append("".join(lines[start:node.end_lineno]).strip("\n"))

    kept.append(new_fn)
    return render_module(connector_id, label, kept)


PREFERRED_BASE_BRANCH = "staging"


def resolve_base_branch(repo: str, token: str) -> str | None:
    """Target ``staging`` when the repository has one, otherwise the repo default.

    House convention is that work branches off staging, so a generated handler
    should arrive where hand-written code arrives and reach production by the same
    route. Left to itself ``github_sync`` targets the repository's DEFAULT branch,
    which on one_bpmn is ``version-15`` — so handlers were skipping staging
    entirely.

    It cannot simply be hardcoded, though. The receiving repository is chosen by
    ``connector_handler_app``, so it need not be one_bpmn and need not have a
    staging branch at all; a repo without one would fail the pull request outright
    on the ref lookup. Returning None hands the decision back to github_sync,
    whose fallback is the default branch — the one branch guaranteed to be there.
    This is why the sibling customization flow passes None unconditionally: it
    syncs to any app's repo, so it can never assume more than the default.
    """
    from one_bpmn.api.github_sync import branch_exists

    try:
        if branch_exists(token=token, repo=repo, branch=PREFERRED_BASE_BRANCH):
            return PREFERRED_BASE_BRANCH
    except Exception:
        # Probing for a nicer base must never be why a handler cannot be
        # delivered. Fall through and let github_sync use the default branch.
        frappe.log_error(
            title="Connector handler: base branch probe failed",
            message=frappe.get_traceback(),
        )
    return None


# ── delivery ─────────────────────────────────────────────────────────────────
def propose_python_handler(
    *,
    connector_id: str,
    operation: str,
    function_name: str,
    code: str,
    summary: str = "",
    connector_label: str = "",
    base_branch: str | None = None,
) -> dict:
    """Validate a handler, open a pull request carrying it, and point the
    operation at it — leaving the connector disabled.

    ``connector_id`` is passed in rather than read from the turn store because a
    handler is often the LAST thing a connector needs, on a later turn than the one
    that wrote it — and because the turn that writes a connector is the turn most
    likely to be busy re-drafting. Tying the two together would make the handler
    reachable only in the one turn least able to reach it.

    The operation row is written even though the handler cannot resolve until the
    pull request merges and the app is deployed. That is deliberate and matches
    what the agent already does with credentials: the configuration records what
    was proposed, the connector stays disabled, and a person turns it on once the
    code is actually there. A silent gap between "the agent said it built this"
    and "anything exists" is the worse failure.

    Returns a dict the calling tool hands straight back to the model.
    """
    app = handler_app()
    result = {
        "ok": False,
        "connector": connector_id,
        "operation": operation,
        "app": app,
        "handler_path": handler_path(connector_id, function_name, app) if app else None,
        "file": repo_path(connector_id, app) if app else None,
    }

    check = validate_handler(code, function_name)
    result["warnings"] = check["warnings"]
    if not check["ok"]:
        result["errors"] = check["errors"]
        result["note"] = _(
            "Nothing was written and no pull request was opened. Fix the handler and call this again."
        )
        return result

    if not app:
        result["errors"] = [
            _(
                "Handler authoring is switched off: no Connector Handler App is set in "
                "Processa Settings, so there is no repository to open a pull request against."
            )
        ]
        result["retryable"] = False
        return result

    connector = frappe.db.get_value(
        "BPMN Connector", {"connector_id": connector_id}, ["name", "label", "enabled"], as_dict=True
    )
    if not connector:
        result["errors"] = [
            _("No BPMN Connector with connector_id '{0}'. Draft and write the connector first.")
            .format(connector_id)
        ]
        return result
    label = connector_label or connector.label or connector_id

    op_name = frappe.db.get_value(
        "BPMN Connector Operation", {"connector": connector.name, "operation_id": operation}, "name"
    )
    if not op_name:
        result["errors"] = [
            _("Connector '{0}' has no operation '{1}'. Write the operation first, then give it a handler.")
            .format(connector_id, operation)
        ]
        return result

    # ── the pull request ────────────────────────────────────────────────────
    from one_bpmn.api.github_sync import open_customization_pr
    from one_bpmn.api.production_review import _allowed_repo_owners, _repo_for_app

    token = frappe.get_cached_doc("Processa Settings").get_password("github_token")
    repo = _repo_for_app(app)
    if not token or not repo:
        result["errors"] = [
            _("Cannot open a pull request: {0}.").format(
                _("no GitHub token in Processa Settings") if not token
                else _("no git remote resolved for app '{0}'").format(app)
            )
        ]
        result["retryable"] = False
        return result

    if not base_branch:
        base_branch = resolve_base_branch(repo, token)

    path = repo_path(connector_id, app)
    stamp = frappe.generate_hash(length=6)
    head_branch = f"processa/connector-handler-{frappe.scrub(connector_id)}-{stamp}"
    title = f"Processa: {connector_id}.{operation} Python handler"
    body = _pr_body(connector_id, label, operation, function_name, path, summary,
                    check["warnings"], app)

    def _build(reader):
        # Read the module as it stands ON THE BRANCH, so a second operation for
        # this connector appends instead of replacing the file wholesale.
        return {path: merge_module(reader(path), connector_id, label, function_name, code)}

    try:
        pr_url = open_customization_pr(
            token=token,
            repo=repo,
            base_branch=base_branch,
            head_branch=head_branch,
            build_files=_build,
            commit_message=title,
            pr_title=title,
            pr_body=body,
            allowed_owners=_allowed_repo_owners(),
        )
    except Exception as exc:
        frappe.log_error(
            title=f"Connector handler PR failed ({connector_id}.{operation})",
            message=frappe.get_traceback(),
        )
        result["errors"] = [_("Opening the pull request failed: {0}").format(exc)]
        result["note"] = _("The operation was left untouched, so nothing points at code that does not exist.")
        if is_permanent_delivery_failure(exc):
            result["retryable"] = False
            result["note"] = _(
                "This is a credentials problem, not a problem with the handler — the code was "
                "accepted. Do NOT call this tool again; it will fail the same way. Report that "
                "the GitHub token in Processa Settings needs renewing, and include the handler "
                "you wrote so the work is not lost."
            )
        return result

    # ── point the operation at the handler, connector stays disabled ────────
    frappe.db.set_value(
        "BPMN Connector Operation", op_name,
        {"execution_type": "Python Handler", "handler_path": result["handler_path"]},
    )
    if connector.enabled:
        frappe.db.set_value("BPMN Connector", connector.name, "enabled", 0)

    result.update({
        "ok": True,
        "pull_request": pr_url,
        "branch": head_branch,
        "repository": repo,
        "connector_enabled": False,
        "note": _(
            "The operation now names the handler and the connector is disabled. The handler "
            "cannot run until the pull request is merged and the app deployed; a person enables "
            "the connector after that."
        ),
    })
    return result


def _pr_body(connector_id, label, operation, function_name, path, summary, warnings, app=None) -> str:
    lines = [
        f"Adds the Python handler for **{label}** operation `{operation}`.",
        "",
        "| | |",
        "|---|---|",
        f"| Connector | `{connector_id}` |",
        f"| Operation | `{operation}` |",
        f"| Handler path | `{handler_path(connector_id, function_name, app)}` |",
        f"| File | `{path}` |",
        "",
    ]
    if summary:
        lines += ["**What it does**", "", summary, ""]
    lines += [
        "**Contract** — the dispatcher resolves `handler_path` with `frappe.get_attr` and calls",
        "`fn(params, ctx)`, where `params` is already Jinja-rendered with value transforms applied.",
        "Whatever is returned becomes the service task's output variable.",
        "",
        "**Before merging**, the reviewer owns what the automated screen does not: whether the",
        "handler is correct, whether its outbound calls and error handling are acceptable, and",
        "whether the operation's declared fields match what it actually reads.",
        "",
        "The connector was left **disabled**. Merging this does not switch anything on — someone",
        "enables it once the code is deployed.",
    ]
    if warnings:
        lines += ["", "**Noted while generating:**", ""] + [f"- {w}" for w in warnings]
    return "\n".join(lines)
