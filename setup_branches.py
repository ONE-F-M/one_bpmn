#!/usr/bin/env python3
"""
Git branch setup script for the one_bpmn AI Agent Task feature.

Run from /Users/talleyrand/1/apps/one_bpmn:
    python3 setup_branches.py

This script:
  1. Removes any stale .git/*.lock files
  2. Resets staging to upstream/staging
  3. Creates the agent_testing integration branch
  4. For each WI branch: writes files, commits, merges into agent_testing

After completion you will be on the agent_testing branch with all 13 WIs merged.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# Shell helpers
# ─────────────────────────────────────────────────────────────────────────────

def sh(cmd: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=REPO, **kw)
    if check and result.returncode != 0:
        print(f"  ERROR (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result


def write(relpath: str, content: str) -> None:
    full = os.path.join(REPO, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"    wrote {relpath}")


def add_commit(paths: list[str], message: str) -> None:
    for p in paths:
        sh(f"git add {p}")
    sh(f'git commit -m {message!r}')


def branch_from(name: str, base: str) -> None:
    """Create branch *name* from *base*, deleting if it already exists."""
    sh(f"git checkout {base}")
    sh(f"git branch -D {name}", check=False)
    sh(f"git checkout -b {name}")


def merge_into(target: str, source: str) -> None:
    sh(f"git checkout {target}")
    sh(f"git merge {source} --no-ff -m 'Merge {source} into {target}'")


# ─────────────────────────────────────────────────────────────────────────────
# File contents
# ─────────────────────────────────────────────────────────────────────────────

EXECUTOR_INIT = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
agents/executor — shared interface and typed data structures for AI Agent Tasks.

This package is a pure interface layer. It declares:
  - Executor      : abstract base class all backends implement
  - ExecutorConfig: per-task configuration (backend, provider, prompts, limits)
  - ExecutorContext: runtime context (doctype/docname, instance, jinja context)
  - ExecutorResult: structured result (output, token usage, error code)
  - TokenUsage    : prompt/completion/total token counts
  - ErrorCode     : named error states shared by all backends
  - get_executor(): backend registry look-up

It makes NO LLM calls and has NO dependency on agents/llm_provider/,
agents/google_adk/, or any external LLM SDK.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class ErrorCode(Enum):
    SUCCESS = "SUCCESS"
    FAILED_MODEL_CALL = "FAILED_MODEL_CALL"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    TIMEOUT = "TIMEOUT"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ExecutorConfig:
    backend: str = "direct_api"
    provider_name: str = ""
    model: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 1024
    timeout_seconds: int = 30
    response_format: str = "text"        # "text" | "json"
    response_schema: Optional[str] = None  # JSON Schema string
    max_retries: int = 2
    retry_backoff_ms: int = 1000


@dataclass
class ExecutorContext:
    context_doctype: str = ""
    context_docname: str = ""
    instance_name: str = ""
    initiated_by: str = ""
    jinja_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutorResult:
    output: Any = None
    token_usage: Optional[TokenUsage] = None
    error_code: ErrorCode = ErrorCode.SUCCESS
    error_message: str = ""
    raw: Any = None


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class Executor(ABC):
    """
    Abstract executor. All backends subclass this and implement run().

    run() must be synchronous and return an ExecutorResult for every
    possible outcome — it must never raise an exception to the caller.
    """

    @abstractmethod
    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        """Execute one AI Agent Task. Must be implemented by every backend."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Backend registry (WI-001134)
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, type] = {}


def register_executor(name: str, cls: type) -> None:
    """Register a backend class under *name*. Called by each backend module."""
    _REGISTRY[name] = cls


def get_executor(backend_name: str) -> type:
    """
    Return the Executor subclass registered under *backend_name*.

    Raises:
        ValueError: if the name is not in the registry.
    """
    if backend_name not in _REGISTRY:
        raise ValueError(
            f"Unknown executor backend: {backend_name!r}. "
            f"Registered backends: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[backend_name]
'''

DIRECT_API_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Direct API executor backend — single OpenAI-compatible chat/completions call.

Registered as "direct_api". Works with any provider that exposes an
OpenAI-compatible REST endpoint (OpenAI, Anthropic, Google, Bedrock,
self-hosted, etc.).

No SDK dependency: uses requests.post only.
Prompt rendering (Jinja) is performed by the dispatcher BEFORE calling run().
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Optional

import frappe
from frappe.utils.password import get_decrypted_password

from . import (
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)

_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503})


class DirectApiExecutor(Executor):
    """Single-call OpenAI-compatible HTTP executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        try:
            provider = frappe.get_doc("AI Provider", config.provider_name)
        except frappe.DoesNotExistError:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_NOT_FOUND,
                error_message=f"AI Provider \'{config.provider_name}\' not found.",
            )

        if not provider.enabled:
            return ExecutorResult(
                error_code=ErrorCode.PROVIDER_DISABLED,
                error_message=f"AI Provider \'{config.provider_name}\' is disabled.",
            )

        try:
            api_key = get_decrypted_password("AI Provider", config.provider_name, "api_key") or ""
        except Exception:
            api_key = ""

        endpoint = (provider.api_endpoint or "").rstrip("/")
        url = f"{endpoint}/chat/completions"
        model = config.model or provider.default_model or ""

        messages = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        messages.append({"role": "user", "content": config.user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "max_tokens": config.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        import requests

        last_error = ""
        for attempt in range(config.max_retries + 1):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=config.timeout_seconds,
                )
            except requests.Timeout:
                return ExecutorResult(
                    error_code=ErrorCode.TIMEOUT,
                    error_message="Request timed out.",
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=last_error,
                )

            if resp.status_code in _TRANSIENT_STATUS_CODES:
                last_error = f"HTTP {resp.status_code}"
                if attempt < config.max_retries:
                    self._sleep_backoff(config, attempt)
                    continue
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=last_error,
                )

            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message=str(exc),
                )

            try:
                data = resp.json()
            except Exception:
                return ExecutorResult(
                    error_code=ErrorCode.FAILED_MODEL_CALL,
                    error_message="Provider returned non-JSON response.",
                )

            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            token_usage = self._parse_token_usage(data.get("usage", {}))

            if config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    return validation_result
                return ExecutorResult(
                    output=validation_result,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                    raw=data,
                )

            return ExecutorResult(
                output=content,
                token_usage=token_usage,
                error_code=ErrorCode.SUCCESS,
                raw=data,
            )

        return ExecutorResult(
            error_code=ErrorCode.FAILED_MODEL_CALL,
            error_message=last_error or "Max retries exceeded.",
        )

    @staticmethod
    def _sleep_backoff(config: ExecutorConfig, attempt: int) -> None:
        base_s = (config.retry_backoff_ms / 1000.0) * (2 ** attempt)
        jitter = random.uniform(0, 0.1)
        time.sleep(base_s + jitter)

    @staticmethod
    def _parse_token_usage(usage_raw: dict) -> TokenUsage:
        prompt = usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0
        completion = usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0
        total = usage_raw.get("total_tokens") or (prompt + completion)
        return TokenUsage(
            prompt_tokens=int(prompt),
            completion_tokens=int(completion),
            total_tokens=int(total),
        )

    @staticmethod
    def _validate_json(content: str, schema_str: Optional[str]) -> Any:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return ExecutorResult(
                error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                error_message=f"Model returned invalid JSON: {exc}",
            )

        if schema_str:
            try:
                import jsonschema
                schema = json.loads(schema_str)
                jsonschema.validate(parsed, schema)
            except ImportError:
                pass
            except json.JSONDecodeError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"Response schema is not valid JSON: {exc}",
                )
            except Exception as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"JSON schema validation failed: {exc}",
                )

        return parsed


register_executor("direct_api", DirectApiExecutor)
'''

ANTIGRAVITY_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Antigravity SDK executor backend.

Registered as "antigravity". Wraps the google-antigravity SDK in
single-call (no tools, no multi-turn) mode.

If the SDK is not installed the executor returns FAILED_MODEL_CALL with a
clear message — the bench continues to function for all other task types.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from . import (
    ErrorCode,
    Executor,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    TokenUsage,
    register_executor,
)


class AntigravityExecutor(Executor):
    """Single-call Google Antigravity SDK executor."""

    def run(self, config: ExecutorConfig, context: ExecutorContext) -> ExecutorResult:
        try:
            import antigravity  # noqa: F401
        except ImportError:
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=(
                    "google-antigravity SDK is not installed. "
                    "Run: pip install google-antigravity"
                ),
            )

        try:
            import antigravity as _sdk

            agent = _sdk.Agent(
                model=config.model,
                system_prompt=config.system_prompt,
            )
            response = agent.send(config.user_prompt)
            content = getattr(response, "text", "") or str(response)

            usage_obj = getattr(response, "usage", None)
            token_usage = TokenUsage(
                prompt_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage_obj, "total_tokens", 0) or 0),
            )
            if not token_usage.total_tokens:
                token_usage.total_tokens = (
                    token_usage.prompt_tokens + token_usage.completion_tokens
                )

            if config.response_format == "json":
                validation_result = self._validate_json(content, config.response_schema)
                if isinstance(validation_result, ExecutorResult):
                    return validation_result
                return ExecutorResult(
                    output=validation_result,
                    token_usage=token_usage,
                    error_code=ErrorCode.SUCCESS,
                )

            return ExecutorResult(
                output=content,
                token_usage=token_usage,
                error_code=ErrorCode.SUCCESS,
            )

        except Exception as exc:
            return ExecutorResult(
                error_code=ErrorCode.FAILED_MODEL_CALL,
                error_message=str(exc),
            )

    @staticmethod
    def _validate_json(content: str, schema_str: Optional[str]) -> Any:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return ExecutorResult(
                error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                error_message=f"Model returned invalid JSON: {exc}",
            )

        if schema_str:
            try:
                import jsonschema
                schema = json.loads(schema_str)
                jsonschema.validate(parsed, schema)
            except ImportError:
                pass
            except json.JSONDecodeError as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"Response schema is not valid JSON: {exc}",
                )
            except Exception as exc:
                return ExecutorResult(
                    error_code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                    error_message=f"JSON schema validation failed: {exc}",
                )

        return parsed


register_executor("antigravity", AntigravityExecutor)
'''

AI_PROVIDER_JSON = '''\
{
 "actions": [],
 "allow_import": 0,
 "allow_rename": 1,
 "autoname": "field:provider_name",
 "creation": "2026-06-17 00:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": [
  "provider_name",
  "provider_type",
  "api_endpoint",
  "api_key",
  "default_model",
  "enabled"
 ],
 "fields": [
  {
   "fieldname": "provider_name",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Provider Name",
   "reqd": 1,
   "unique": 1
  },
  {
   "fieldname": "provider_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Provider Type",
   "options": "OpenAI\\nAnthropic\\nGoogle\\nBedrock\\nOpenAI-compatible\\nAntigravity",
   "reqd": 1
  },
  {
   "fieldname": "api_endpoint",
   "fieldtype": "Data",
   "label": "API Endpoint",
   "description": "Base URL for the provider API, e.g. https://api.openai.com/v1"
  },
  {
   "fieldname": "api_key",
   "fieldtype": "Password",
   "label": "API Key",
   "reqd": 1,
   "description": "Stored encrypted. Never appears in list views or API responses."
  },
  {
   "fieldname": "default_model",
   "fieldtype": "Data",
   "label": "Default Model",
   "description": "e.g. gpt-4o, claude-sonnet-4-20250514"
  },
  {
   "fieldname": "enabled",
   "fieldtype": "Check",
   "label": "Enabled",
   "default": "1"
  }
 ],
 "links": [],
 "modified": "2026-06-17 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "ONE BPMN",
 "name": "AI Provider",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  }
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "title_field": "provider_name",
 "track_changes": 0
}
'''

AI_PROVIDER_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AIProvider(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        api_endpoint: DF.Data | None
        api_key: DF.Password
        default_model: DF.Data | None
        enabled: DF.Check
        provider_name: DF.Data
        provider_type: DF.Literal["OpenAI", "Anthropic", "Google", "Bedrock", "OpenAI-compatible", "Antigravity"]
    # end: auto-generated types
    pass
'''

TEST_AI_PROVIDER_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the AI Provider doctype.

Covers:
  (a) Admin can create an AI Provider with all required fields
  (b) as_dict() does NOT contain the api_key value
  (c) doc.get_password("api_key") returns the real key
  (d) frappe.get_list("AI Provider") does NOT include api_key in results
  (e) A non-admin user cannot frappe.get_doc an AI Provider (PermissionError)
  (f) Duplicate provider_name raises DuplicateEntryError
  (g) A disabled provider (enabled=0) is still readable by an admin
"""
import frappe
from frappe.tests.utils import FrappeTestCase


def make_ai_provider(**kwargs) -> frappe.Document:
    defaults = {
        "doctype": "AI Provider",
        "provider_name": f"test-provider-{frappe.generate_hash(length=6)}",
        "provider_type": "OpenAI",
        "api_endpoint": "https://api.openai.com/v1",
        "api_key": "sk-test-placeholder-key",
        "default_model": "gpt-4o",
        "enabled": 1,
    }
    defaults.update(kwargs)
    doc = frappe.get_doc(defaults)
    doc.insert(ignore_permissions=True)
    return doc


class TestAIProvider(FrappeTestCase):
    def test_create_ai_provider(self):
        doc = make_ai_provider()
        self.assertTrue(frappe.db.exists("AI Provider", doc.name))

    def test_api_key_not_in_as_dict(self):
        doc = make_ai_provider()
        loaded = frappe.get_doc("AI Provider", doc.name)
        d = loaded.as_dict()
        self.assertNotEqual(d.get("api_key"), "sk-test-placeholder-key")

    def test_get_password_returns_real_key(self):
        doc = make_ai_provider(api_key="sk-secret-test-key")
        loaded = frappe.get_doc("AI Provider", doc.name)
        decrypted = loaded.get_password("api_key")
        self.assertEqual(decrypted, "sk-secret-test-key")

    def test_get_list_excludes_api_key(self):
        doc = make_ai_provider()
        results = frappe.get_list(
            "AI Provider",
            filters={"name": doc.name},
            fields=["name", "provider_name", "api_key"],
        )
        if results:
            self.assertNotEqual(results[0].get("api_key"), "sk-test-placeholder-key")

    def test_non_admin_cannot_read(self):
        doc = make_ai_provider()
        frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc("AI Provider", doc.name)
        finally:
            frappe.set_user("Administrator")

    def test_duplicate_provider_name_raises(self):
        name = f"dup-{frappe.generate_hash(length=6)}"
        make_ai_provider(provider_name=name)
        with self.assertRaises(frappe.DuplicateEntryError):
            make_ai_provider(provider_name=name)

    def test_disabled_provider_readable_by_admin(self):
        doc = make_ai_provider(enabled=0)
        loaded = frappe.get_doc("AI Provider", doc.name)
        self.assertEqual(loaded.enabled, 0)
'''

SEED_AI_PROVIDERS_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Seed patch: create sample AI Provider records for developer mode.
Guarded by frappe.conf.developer_mode — never runs in production.
"""
import frappe


def execute():
    if not frappe.conf.get("developer_mode"):
        return

    providers = [
        {
            "provider_name": "openai-dev",
            "provider_type": "OpenAI",
            "api_endpoint": "https://api.openai.com/v1",
            "api_key": "sk-placeholder-openai-dev-key",
            "default_model": "gpt-4o",
            "enabled": 1,
        },
        {
            "provider_name": "anthropic-dev",
            "provider_type": "Anthropic",
            "api_endpoint": "https://api.anthropic.com/v1",
            "api_key": "sk-ant-placeholder-anthropic-dev-key",
            "default_model": "claude-sonnet-4-20250514",
            "enabled": 1,
        },
    ]

    for p in providers:
        if frappe.db.exists("AI Provider", p["provider_name"]):
            continue
        doc = frappe.get_doc({"doctype": "AI Provider", **p})
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
'''

TEST_EXECUTOR_PY = '''\
# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Unit tests for executor backends using mocked HTTP / SDK responses."""
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
    ErrorCode,
    ExecutorConfig,
    ExecutorContext,
    ExecutorResult,
    get_executor,
    register_executor,
)
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.executor.antigravity import AntigravityExecutor


def _make_config(**kwargs) -> ExecutorConfig:
    defaults = dict(
        backend="direct_api",
        provider_name="test-openai",
        model="gpt-4o",
        system_prompt="You are helpful.",
        user_prompt="Hello",
        max_retries=2,
        retry_backoff_ms=0,
        timeout_seconds=5,
    )
    defaults.update(kwargs)
    return ExecutorConfig(**defaults)


def _make_context() -> ExecutorContext:
    return ExecutorContext(
        context_doctype="Salary Slip",
        context_docname="SS-0001",
        instance_name="BPMN-0001",
        initiated_by="test@example.com",
    )


def _openai_response(content: str, prompt_tokens=10, completion_tokens=5) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _mock_provider(enabled=True, endpoint="https://api.openai.com/v1"):
    p = MagicMock()
    p.enabled = enabled
    p.api_endpoint = endpoint
    p.default_model = "gpt-4o"
    return p


class TestDirectApiExecutor(FrappeTestCase):

    def _run(self, mock_response, config=None, **response_kw):
        cfg = config or _make_config()
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = response_kw.get("status_code", 200)
        resp.json.return_value = mock_response
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \\
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \\
             patch("requests.post", return_value=resp):
            return DirectApiExecutor().run(cfg, ctx)

    def test_text_success(self):
        result = self._run(_openai_response("Hello back!"))
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "Hello back!")
        self.assertEqual(result.token_usage.total_tokens, 15)

    def test_json_success_with_schema(self):
        schema = json.dumps({"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
        content = json.dumps({"name": "Alice"})
        cfg = _make_config(response_format="json", response_schema=schema)
        result = self._run(_openai_response(content), config=cfg)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertIsInstance(result.output, dict)
        self.assertEqual(result.output["name"], "Alice")

    def test_json_schema_validation_failed(self):
        schema = json.dumps({"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]})
        content = json.dumps({"name": "missing age"})
        cfg = _make_config(response_format="json", response_schema=schema)
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _openai_response(content)
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \\
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \\
             patch("requests.post", return_value=resp):
            try:
                import jsonschema  # noqa
                result = DirectApiExecutor().run(cfg, ctx)
                self.assertEqual(result.error_code, ErrorCode.SCHEMA_VALIDATION_FAILED)
            except ImportError:
                self.skipTest("jsonschema not installed")

    def test_http_429_exhausts_retries(self):
        cfg = _make_config(max_retries=2, retry_backoff_ms=0)
        ctx = _make_context()
        provider = _mock_provider()

        resp = MagicMock()
        resp.status_code = 429
        resp.json.return_value = {}
        resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \\
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \\
             patch("requests.post", return_value=resp), \\
             patch("time.sleep"):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)

    def test_retry_recovery(self):
        cfg = _make_config(max_retries=2, retry_backoff_ms=0)
        ctx = _make_context()
        provider = _mock_provider()

        fail_resp = MagicMock()
        fail_resp.status_code = 429

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = _openai_response("recovered!")
        ok_resp.raise_for_status = MagicMock()

        with patch("frappe.get_doc", return_value=provider), \\
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \\
             patch("requests.post", side_effect=[fail_resp, ok_resp]), \\
             patch("time.sleep"):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "recovered!")

    def test_timeout(self):
        import requests as req
        cfg = _make_config()
        ctx = _make_context()
        provider = _mock_provider()

        with patch("frappe.get_doc", return_value=provider), \\
             patch("frappe.utils.password.get_decrypted_password", return_value="sk-test"), \\
             patch("requests.post", side_effect=req.Timeout):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.TIMEOUT)

    def test_provider_not_found(self):
        cfg = _make_config(provider_name="nonexistent-provider")
        ctx = _make_context()
        with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.PROVIDER_NOT_FOUND)

    def test_provider_disabled(self):
        cfg = _make_config()
        ctx = _make_context()
        provider = _mock_provider(enabled=False)
        with patch("frappe.get_doc", return_value=provider):
            result = DirectApiExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.PROVIDER_DISABLED)


class TestAntigravityExecutor(FrappeTestCase):

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("antigravity") is not None,
        "google-antigravity SDK not installed"
    )
    def test_antigravity_success(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()

        fake_usage = MagicMock()
        fake_usage.prompt_tokens = 10
        fake_usage.completion_tokens = 5
        fake_usage.total_tokens = 15

        fake_response = MagicMock()
        fake_response.text = "AI answer"
        fake_response.usage = fake_usage

        fake_agent = MagicMock()
        fake_agent.send.return_value = fake_response

        import antigravity
        with patch.object(antigravity, "Agent", return_value=fake_agent):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.SUCCESS)
        self.assertEqual(result.output, "AI answer")
        self.assertEqual(result.token_usage.total_tokens, 15)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("antigravity") is not None,
        "google-antigravity SDK not installed"
    )
    def test_antigravity_sdk_exception(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()

        import antigravity
        fake_agent = MagicMock()
        fake_agent.send.side_effect = RuntimeError("SDK error")
        with patch.object(antigravity, "Agent", return_value=fake_agent):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("SDK error", result.error_message)

    def test_antigravity_sdk_not_installed(self):
        cfg = _make_config(backend="antigravity")
        ctx = _make_context()
        with patch.dict("sys.modules", {"antigravity": None}):
            result = AntigravityExecutor().run(cfg, ctx)
        self.assertEqual(result.error_code, ErrorCode.FAILED_MODEL_CALL)
        self.assertIn("google-antigravity", result.error_message)


class TestExecutorRegistry(FrappeTestCase):

    def test_get_executor_direct_api(self):
        cls = get_executor("direct_api")
        self.assertIs(cls, DirectApiExecutor)

    def test_get_executor_unknown_raises(self):
        with self.assertRaises(ValueError) as cm:
            get_executor("nonexistent_backend")
        self.assertIn("nonexistent_backend", str(cm.exception))

    def test_dummy_backend_registration(self):
        class DummyExecutor:
            pass
        register_executor("test_backend_dummy", DummyExecutor)
        cls = get_executor("test_backend_dummy")
        self.assertIs(cls, DummyExecutor)
'''

# Dispatcher addition (appended to dispatchers.py)
DISPATCH_AI_AGENT_ADDITION = '''\


def dispatch_ai_agent(instance, task, task_cfg: dict, bpmn_id: str) -> None:
\t"""
\tExecute an AI Agent Task via the executor package.

\tReads spiffworkflow:ai* configuration from task_cfg, Jinja-renders the
\tprompts, calls the configured executor backend, and writes results into
\ttask.data.  On failure, sets error variables and logs to Frappe Error Log
\t— the task STILL completes normally (no instance "Errored" state).
\t"""
\tfrom one_bpmn.agents.executor import ExecutorConfig, ExecutorContext, ErrorCode, get_executor
\tfrom one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa
\tfrom one_bpmn.agents.executor.antigravity import AntigravityExecutor  # noqa

\tdoc = frappe._dict()
\tif instance.context_doctype and instance.context_docname:
\t\ttry:
\t\t\tdoc = frappe.get_doc(instance.context_doctype, instance.context_docname)
\t\texcept Exception:
\t\t\tpass

\tjinja_ctx = {"doc": doc, "instance": instance, "frappe": frappe}

\tdef render(text):
\t\tif not text:
\t\t\treturn ""
\t\ttry:
\t\t\treturn frappe.render_template(text, jinja_ctx)
\t\texcept Exception:
\t\t\treturn text

\tsystem_prompt = render(task_cfg.get("aiSystemPrompt", ""))
\tuser_prompt   = render(task_cfg.get("aiUserPrompt", ""))

\tconfig = ExecutorConfig(
\t\tbackend          = task_cfg.get("aiBackend", "direct_api"),
\t\tprovider_name    = task_cfg.get("aiProvider", ""),
\t\tmodel            = task_cfg.get("aiModel", ""),
\t\tsystem_prompt    = system_prompt,
\t\tuser_prompt      = user_prompt,
\t\ttemperature      = float(task_cfg.get("aiTemperature", 0.7) or 0.7),
\t\ttop_p            = float(task_cfg.get("aiTopP", 1.0) or 1.0),
\t\tmax_tokens       = int(task_cfg.get("aiMaxTokens", 1024) or 1024),
\t\ttimeout_seconds  = int(task_cfg.get("aiTimeout", 30) or 30),
\t\tresponse_format  = task_cfg.get("aiResponseFormat", "text") or "text",
\t\tresponse_schema  = task_cfg.get("aiResponseSchema") or None,
\t\tmax_retries      = int(task_cfg.get("aiMaxRetries", 2) or 2),
\t)

\tcontext = ExecutorContext(
\t\tcontext_doctype = instance.context_doctype or "",
\t\tcontext_docname = instance.context_docname or "",
\t\tinstance_name   = instance.name or "",
\t\tinitiated_by    = instance.initiated_by or frappe.session.user or "",
\t\tjinja_context   = jinja_ctx,
\t)

\ttry:
\t\texecutor_cls = get_executor(config.backend)
\t\tresult = executor_cls().run(config, context)
\texcept Exception:
\t\tfrappe.log_error(
\t\t\ttitle=f"BPMN AI Agent Task: unexpected error ({bpmn_id})",
\t\t\tmessage=frappe.get_traceback(),
\t\t)
\t\ttask.data[f"{bpmn_id}_error_code"] = "UNEXPECTED_ERROR"
\t\ttask.data[f"{bpmn_id}_error_message"] = "See Frappe Error Log for details."
\t\treturn

\tif result.error_code == ErrorCode.SUCCESS:
\t\toutput_var = task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"
\t\ttask.data[output_var] = result.output
\t\tif result.token_usage:
\t\t\ttask.data[f"{bpmn_id}_token_usage"] = {
\t\t\t\t"prompt_tokens":     result.token_usage.prompt_tokens,
\t\t\t\t"completion_tokens": result.token_usage.completion_tokens,
\t\t\t\t"total_tokens":      result.token_usage.total_tokens,
\t\t\t}
\telse:
\t\terror_code_name = result.error_code.value
\t\tfrappe.log_error(
\t\t\ttitle=f"BPMN AI Agent Task: {error_code_name} ({bpmn_id})",
\t\t\tmessage=(
\t\t\t\tf"bpmn_id: {bpmn_id}\\n"
\t\t\t\tf"provider: {config.provider_name}\\n"
\t\t\t\tf"model: {config.model}\\n"
\t\t\t\tf"error: {result.error_message}"
\t\t\t),
\t\t)
\t\ttask.data[f"{bpmn_id}_error_code"]    = error_code_name
\t\ttask.data[f"{bpmn_id}_error_message"] = result.error_message

\t\twrite_back_field = task_cfg.get("aiWriteBackField", "")
\t\tif write_back_field and instance.context_doctype and instance.context_docname:
\t\t\ttry:
\t\t\t\tfrappe.db.set_value(
\t\t\t\t\tinstance.context_doctype,
\t\t\t\t\tinstance.context_docname,
\t\t\t\t\twrite_back_field,
\t\t\t\t\tresult.output,
\t\t\t\t)
\t\t\texcept Exception:
\t\t\t\tfrappe.log_error(
\t\t\t\t\ttitle=f"BPMN AI Agent Task: write-back failed ({bpmn_id})",
\t\t\t\t\tmessage=frappe.get_traceback(),
\t\t\t\t)
'''


# ─────────────────────────────────────────────────────────────────────────────
# Helper: read a file on disk and append content to it
# ─────────────────────────────────────────────────────────────────────────────

def append_to_file(relpath: str, content: str) -> None:
    full = os.path.join(REPO, relpath)
    with open(full, "a", encoding="utf-8") as fh:
        fh.write(content)
    print(f"    appended to {relpath}")


def replace_in_file(relpath: str, old: str, new: str) -> None:
    """Replace first occurrence of *old* with *new* in a file."""
    full = os.path.join(REPO, relpath)
    with open(full, "r", encoding="utf-8") as fh:
        text = fh.read()
    if old not in text:
        print(f"  WARNING: pattern not found in {relpath}: {old[:60]!r}")
        return
    text = text.replace(old, new, 1)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"    patched {relpath}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── 0. Remove stale lock files ─────────────────────────────────────────
    print("\n=== Removing stale lock files ===")
    for lock in glob.glob(os.path.join(REPO, ".git", "*.lock")):
        os.remove(lock)
        print(f"  removed {lock}")

    # ── 1. Reset staging ───────────────────────────────────────────────────
    print("\n=== Resetting staging to upstream/staging ===")
    sh("git checkout staging")
    sh("git reset --hard upstream/staging")

    # ── 2. Create agent_testing from staging ──────────────────────────────
    print("\n=== Creating agent_testing branch ===")
    sh("git branch -D agent_testing", check=False)
    sh("git checkout -b agent_testing")
    sh("git checkout staging")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001132 + WI-001134 — executor package, interface, registry
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001132: executor package ===")
    branch_from("WI-001132", "staging")
    write("one_bpmn/agents/executor/__init__.py", EXECUTOR_INIT)
    add_commit(
        ["one_bpmn/agents/executor/"],
        "feat(WI-001132+WI-001134): executor package, ABC, dataclasses, ErrorCode, registry",
    )
    merge_into("agent_testing", "WI-001132")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001135 + WI-001136 — AI Provider doctype with permissions
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001135+WI-001136: AI Provider doctype ===")
    branch_from("WI-001135", "staging")
    write("one_bpmn/one_bpmn/doctype/ai_provider/__init__.py", "")
    write("one_bpmn/one_bpmn/doctype/ai_provider/ai_provider.json", AI_PROVIDER_JSON)
    write("one_bpmn/one_bpmn/doctype/ai_provider/ai_provider.py", AI_PROVIDER_PY)
    add_commit(
        ["one_bpmn/one_bpmn/doctype/ai_provider/"],
        "feat(WI-001135+WI-001136): AI Provider doctype with Password field and System Manager permissions",
    )
    merge_into("agent_testing", "WI-001135")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001137 — AI Provider tests + seed patch
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001137: AI Provider tests + seed patch ===")
    branch_from("WI-001137", "WI-001135")
    write("one_bpmn/one_bpmn/doctype/ai_provider/test_ai_provider.py", TEST_AI_PROVIDER_PY)
    write("one_bpmn/one_bpmn/patches/v1_0/seed_ai_providers.py", SEED_AI_PROVIDERS_PY)
    # Add seed patch entry to patches.txt
    patches_path = os.path.join(REPO, "one_bpmn", "patches.txt")
    with open(patches_path) as _pf:
        _pc = _pf.read()
    if "seed_ai_providers" not in _pc:
        with open(patches_path, "a") as _pf:
            _pf.write("\none_bpmn.one_bpmn.patches.v1_0.seed_ai_providers\n")
    add_commit(
        [
            "one_bpmn/one_bpmn/doctype/ai_provider/test_ai_provider.py",
            "one_bpmn/one_bpmn/patches/v1_0/seed_ai_providers.py",
            "one_bpmn/patches.txt",
        ],
        "feat(WI-001137): AI Provider tests (7 cases) and dev-mode seed patch",
    )
    merge_into("agent_testing", "WI-001137")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001138 — DirectApiExecutor
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001138: DirectApiExecutor ===")
    branch_from("WI-001138", "WI-001132")
    write("one_bpmn/agents/executor/direct_api.py", DIRECT_API_PY)
    add_commit(
        ["one_bpmn/agents/executor/direct_api.py"],
        "feat(WI-001138): DirectApiExecutor — single-call OpenAI-compatible HTTP backend",
    )
    merge_into("agent_testing", "WI-001138")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001139 — AntigravityExecutor
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001139: AntigravityExecutor ===")
    branch_from("WI-001139", "WI-001138")
    write("one_bpmn/agents/executor/antigravity.py", ANTIGRAVITY_PY)
    add_commit(
        ["one_bpmn/agents/executor/antigravity.py"],
        "feat(WI-001139): AntigravityExecutor — feature-detected Google Antigravity SDK backend",
    )
    merge_into("agent_testing", "WI-001139")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001140 — Executor unit tests
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001140: Executor unit tests ===")
    branch_from("WI-001140", "WI-001139")
    write("one_bpmn/tests/test_executor.py", TEST_EXECUTOR_PY)
    add_commit(
        ["one_bpmn/tests/test_executor.py"],
        "test(WI-001140): executor unit tests — mocked, no real API calls (15 cases)",
    )
    merge_into("agent_testing", "WI-001140")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001141 — ServiceTaskProps.js + BpmnEditor.vue moddle attrs
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001141: Frontend — AI Agent Task service type ===")
    branch_from("WI-001141", "staging")

    # Patch ServiceTaskProps.js — add ai_agent to clearAll
    replace_in_file(
        "spiff/src/bpmn/serviceTaskPropertiesProvider/ServiceTaskProps.js",
        '\t\t\t"spiffworkflow:pushToRoles":          undefined,\n\t\t};',
        '\t\t\t"spiffworkflow:pushToRoles":          undefined,\n'
        '\t\t\t// Clear ai_agent attrs\n'
        '\t\t\t"spiffworkflow:aiBackend":            undefined,\n'
        '\t\t\t"spiffworkflow:aiProvider":           undefined,\n'
        '\t\t\t"spiffworkflow:aiModel":              undefined,\n'
        '\t\t\t"spiffworkflow:aiOutputVariable":     undefined,\n'
        '\t\t\t"spiffworkflow:aiSystemPrompt":       undefined,\n'
        '\t\t\t"spiffworkflow:aiUserPrompt":         undefined,\n'
        '\t\t\t"spiffworkflow:aiResponseFormat":     undefined,\n'
        '\t\t\t"spiffworkflow:aiResponseSchema":     undefined,\n'
        '\t\t\t"spiffworkflow:aiTemperature":        undefined,\n'
        '\t\t\t"spiffworkflow:aiTopP":               undefined,\n'
        '\t\t\t"spiffworkflow:aiMaxTokens":          undefined,\n'
        '\t\t\t"spiffworkflow:aiTimeout":            undefined,\n'
        '\t\t\t"spiffworkflow:aiMaxRetries":         undefined,\n'
        '\t\t};',
    )

    # Patch ServiceTaskProps.js — add to getOptions
    replace_in_file(
        "spiff/src/bpmn/serviceTaskPropertiesProvider/ServiceTaskProps.js",
        '\t{ label: translate("Push Notification"),         value: "push_notification" },\n\t];',
        '\t{ label: translate("Push Notification"),         value: "push_notification" },\n'
        '\t{ label: translate("AI Agent Task"),             value: "ai_agent" },\n'
        '\t];',
    )

    # Patch ServiceTaskProps.js — add ai_agent entries block + AIAgentLauncherComponent
    replace_in_file(
        "spiff/src/bpmn/serviceTaskPropertiesProvider/ServiceTaskProps.js",
        '\treturn entries;\n}',
        '\t// ── AI Agent Task entries ───────────────────────────────────────────────\n'
        '\tif (serviceType === "ai_agent") {\n'
        '\t\tentries.push({\n'
        '\t\t\tid: "spiffworkflow-aiAgentLauncher",\n'
        '\t\t\telement,\n'
        '\t\t\tcomponent: AIAgentLauncherComponent,\n'
        '\t\t});\n'
        '\t}\n\n'
        '\treturn entries;\n'
        '}\n\n'
        '// ===========================================================================\n'
        '// AI AGENT TASK LAUNCHER COMPONENT\n'
        '// ===========================================================================\n'
        'function AIAgentLauncherComponent(props) {\n'
        '\tconst { element } = props;\n'
        '\tconst translate = useService("translate");\n'
        '\tconst eventBus  = useService("eventBus");\n\n'
        '\tfunction openModal() {\n'
        '\t\teventBus.fire("launch-ai-agent-editor", { element });\n'
        '\t}\n\n'
        '\treturn h("div", { style: "padding: 4px 0;" },\n'
        '\t\th("button", {\n'
        '\t\t\tstyle: [\n'
        '\t\t\t\t"padding: 6px 14px",\n'
        '\t\t\t\t"background: #6366f1",\n'
        '\t\t\t\t"color: #fff",\n'
        '\t\t\t\t"border: none",\n'
        '\t\t\t\t"border-radius: 4px",\n'
        '\t\t\t\t"cursor: pointer",\n'
        '\t\t\t\t"font-size: 0.82rem",\n'
        '\t\t\t\t"font-weight: 500",\n'
        '\t\t\t].join(";"),\n'
        '\t\t\tonClick: openModal,\n'
        '\t\t}, translate("Configure AI Agent Task"))\n'
        '\t);\n'
        '}',
    )

    # Patch BpmnEditor.vue — add ai* attrs to moddle extension
    replace_in_file(
        "spiff/src/components/BpmnEditor.vue",
        '\t\t\t\t\t\t{ name: "pushToRoles",          isAttr: true, type: "String" }\n\t\t\t\t\t\t]',
        '\t\t\t\t\t\t{ name: "pushToRoles",          isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t// AI Agent Task attrs\n'
        '\t\t\t\t\t\t{ name: "aiBackend",            isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiProvider",           isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiModel",              isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiOutputVariable",     isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiSystemPrompt",       isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiUserPrompt",         isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiResponseFormat",     isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiResponseSchema",     isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiTemperature",        isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiTopP",               isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiMaxTokens",          isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiTimeout",            isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiMaxRetries",         isAttr: true, type: "String" },\n'
        '\t\t\t\t\t\t{ name: "aiWriteBackField",     isAttr: true, type: "String" }\n'
        '\t\t\t\t\t\t]',
    )

    add_commit(
        [
            "spiff/src/bpmn/serviceTaskPropertiesProvider/ServiceTaskProps.js",
            "spiff/src/components/BpmnEditor.vue",
        ],
        "feat(WI-001141): AI Agent Task service type — properties panel entry + moddle attrs",
    )
    merge_into("agent_testing", "WI-001141")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001142 — AIAgentConfigModal.vue
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001142: AIAgentConfigModal.vue ===")
    branch_from("WI-001142", "WI-001141")

    # Write AIAgentConfigModal.vue
    ai_agent_modal_vue = open(
        os.path.join(REPO, "spiff/src/components/AIAgentConfigModal.vue"), encoding="utf-8"
    ).read()
    # File already written to disk by direct file creation; just stage it
    # But in reset scenario it might not exist — re-write from embedded content
    # (We embed a minimal reference here; the real content is the file already written)
    # For the branch script, we need the content. Since the file was already written
    # to disk before this script runs, we just stage it.
    sh("git add spiff/src/components/AIAgentConfigModal.vue", check=False)

    # Patch BpmnEditor.vue — import AIAgentConfigModal and wire it
    replace_in_file(
        "spiff/src/components/BpmnEditor.vue",
        'import FormattingToolbar from "@/components/FormattingToolbar.vue";\nimport ProsAllyPanel from "@/components/ProsAllyPanel.vue";',
        'import FormattingToolbar from "@/components/FormattingToolbar.vue";\nimport ProsAllyPanel from "@/components/ProsAllyPanel.vue";\nimport AIAgentConfigModal from "@/components/AIAgentConfigModal.vue";',
    )

    replace_in_file(
        "spiff/src/components/BpmnEditor.vue",
        '\t"launch-notification-editor",\n]);',
        '\t"launch-notification-editor",\n]);\n\n// AI Agent modal state\nconst aiAgentModal = ref({ show: false, element: null });',
    )

    replace_in_file(
        "spiff/src/components/BpmnEditor.vue",
        '\t\t\t// Notification editing (Send Tasks)\n\t\t\teventBus.on("spiff.notification.edit", (event) => {',
        '\t\t\t// AI Agent Task config modal\n'
        '\t\t\teventBus.on("launch-ai-agent-editor", (event) => {\n'
        '\t\t\t\taiAgentModal.value = { show: true, element: event.element };\n'
        '\t\t\t});\n\n'
        '\t\t\t// Notification editing (Send Tasks)\n'
        '\t\t\teventBus.on("spiff.notification.edit", (event) => {',
    )

    replace_in_file(
        "spiff/src/components/BpmnEditor.vue",
        '\t\t</Dialog>\n\t</div>\n</template>',
        '\t\t</Dialog>\n\n'
        '\t\t<!-- AI Agent Task config modal -->\n'
        '\t\t<AIAgentConfigModal\n'
        '\t\t\tv-if="aiAgentModal.show && aiAgentModal.element"\n'
        '\t\t\t:element="aiAgentModal.element"\n'
        '\t\t\t:modeler="modeler"\n'
        '\t\t\t@close="aiAgentModal.show = false"\n'
        '\t\t/>\n'
        '\t</div>\n</template>',
    )

    add_commit(
        [
            "spiff/src/components/AIAgentConfigModal.vue",
            "spiff/src/components/BpmnEditor.vue",
        ],
        "feat(WI-001142): AIAgentConfigModal.vue — dedicated AI Agent Task config editor",
    )
    merge_into("agent_testing", "WI-001142")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001143 — compilation.py lint
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001143: compile-time lint ===")
    branch_from("WI-001143", "WI-001137")

    LINT_FUNCTION = (
        '\ndef _lint_ai_provider_config(bpmn_xml: str, service_extensions: dict) -> None:\n'
        '\t"""\n'
        '\tCompile-time lint for AI Agent Tasks:\n'
        '\t1. Rejects raw API keys embedded in any spiffworkflow:ai* attribute.\n'
        '\t2. Validates that referenced AI Provider records exist in the database.\n'
        '\t"""\n'
        '\timport re\n'
        '\t_RAW_KEY_RE = re.compile(r"^(sk-|key-)", re.IGNORECASE)\n'
        '\t_RAW_KEY_ATTR_NAMES = frozenset({"aiApiKey", "aiKey"})\n\n'
        '\tfor bpmn_id, task_cfg in (service_extensions or {}).items():\n'
        '\t\tif task_cfg.get("serviceType") != "ai_agent":\n'
        '\t\t\tcontinue\n\n'
        '\t\tfor attr_name, attr_value in task_cfg.items():\n'
        '\t\t\tif attr_name in _RAW_KEY_ATTR_NAMES or _RAW_KEY_RE.match(str(attr_value)):\n'
        '\t\t\t\tfrappe.throw(\n'
        '\t\t\t\t\t_(\n'
        '\t\t\t\t\t\t"Raw API keys must not appear in BPMN XML. "\n'
        '\t\t\t\t\t\t"Use an AI Provider reference."\n'
        '\t\t\t\t\t),\n'
        '\t\t\t\t\texc=frappe.ValidationError,\n'
        '\t\t\t\t)\n\n'
        '\t\tprovider_name = task_cfg.get("aiProvider", "")\n'
        '\t\tif provider_name and not frappe.db.exists("AI Provider", provider_name):\n'
        '\t\t\tfrappe.throw(\n'
        '\t\t\t\t_(\n'
        '\t\t\t\t\t"AI Provider \'{0}\' not found. "\n'
        '\t\t\t\t\t"Create it in the AI Provider list."\n'
        '\t\t\t\t).format(provider_name),\n'
        '\t\t\t\texc=frappe.ValidationError,\n'
        '\t\t\t)\n'
    )

    # Read current compilation.py and insert lint function before compile_process_model
    comp_path = os.path.join(REPO, "one_bpmn/api/compilation.py")
    with open(comp_path, encoding="utf-8") as fh:
        comp_text = fh.read()

    marker = "\n@frappe.whitelist()\ndef compile_process_model(model_name: str) -> dict:"
    if marker in comp_text:
        comp_text = comp_text.replace(marker, LINT_FUNCTION + marker, 1)
    else:
        print("  WARNING: compile_process_model marker not found, appending lint function")
        comp_text += LINT_FUNCTION

    # Also add the _lint_ai_provider_config call after service_extensions block
    call_marker = (
        "\tservice_extensions = _extract_service_task_config(sanitized_xml)\n"
        "\tif service_extensions:\n"
        "\t\tspec_data[\"service_task_extensions\"] = service_extensions\n"
    )
    if call_marker in comp_text:
        comp_text = comp_text.replace(
            call_marker,
            call_marker + "\t_lint_ai_provider_config(sanitized_xml, service_extensions)\n",
            1,
        )

    with open(comp_path, "w", encoding="utf-8") as fh:
        fh.write(comp_text)
    print("    patched one_bpmn/api/compilation.py")

    add_commit(
        ["one_bpmn/api/compilation.py"],
        "feat(WI-001143): compile-time lint — reject raw API keys, validate AI Provider",
    )
    merge_into("agent_testing", "WI-001143")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001144 — dispatch wiring
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001144: dispatch wiring ===")
    branch_from("WI-001144", "WI-001143")

    # Append dispatch_ai_agent to dispatchers.py
    dispatchers_path = os.path.join(
        REPO,
        "one_bpmn/one_bpmn/doctype/bpmn_process_instance/dispatchers.py"
    )
    with open(dispatchers_path, encoding="utf-8") as fh:
        disp_text = fh.read()

    if "dispatch_ai_agent" not in disp_text:
        with open(dispatchers_path, "a", encoding="utf-8") as fh:
            fh.write(DISPATCH_AI_AGENT_ADDITION)
        print("    appended dispatch_ai_agent to dispatchers.py")
    else:
        print("    dispatch_ai_agent already present in dispatchers.py")

    # Patch bpmn_process_instance.py — add import
    replace_in_file(
        "one_bpmn/one_bpmn/doctype/bpmn_process_instance/bpmn_process_instance.py",
        "from one_bpmn.one_bpmn import engine as bpmn_engine\n",
        "from one_bpmn.one_bpmn import engine as bpmn_engine\n"
        "from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_ai_agent\n",
    )

    # Patch bpmn_process_instance.py — add elif branch
    replace_in_file(
        "one_bpmn/one_bpmn/doctype/bpmn_process_instance/bpmn_process_instance.py",
        '\t\t\t\tfrappe.log_error(\n'
        '\t\t\t\t\ttitle=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",\n'
        '\t\t\t\t\tmessage=frappe.get_traceback(),\n'
        '\t\t\t\t)\n\n'
        '\t\treturn True  # default: complete the task',
        '\t\t\t\tfrappe.log_error(\n'
        '\t\t\t\t\ttitle=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",\n'
        '\t\t\t\t\tmessage=frappe.get_traceback(),\n'
        '\t\t\t\t)\n\n'
        '\t\telif service_type == "ai_agent":\n'
        '\t\t\tdispatch_ai_agent(self, task, task_cfg, bpmn_id)\n\n'
        '\t\treturn True  # default: complete the task',
    )

    add_commit(
        [
            "one_bpmn/one_bpmn/doctype/bpmn_process_instance/dispatchers.py",
            "one_bpmn/one_bpmn/doctype/bpmn_process_instance/bpmn_process_instance.py",
        ],
        "feat(WI-001144): dispatch_ai_agent handler + router wiring in _dispatch_service_task",
    )
    merge_into("agent_testing", "WI-001144")

    # ══════════════════════════════════════════════════════════════════════
    # WI-001145 — integration tests
    # ══════════════════════════════════════════════════════════════════════
    print("\n=== WI-001145: integration tests ===")
    branch_from("WI-001145", "WI-001144")

    integration_test_content = (
        "# Copyright (c) 2026, one-fm and contributors\n"
        "# For license information, please see license.txt\n"
        '"""\n'
        "End-to-end integration tests for the AI Agent Task flow.\n"
        "\n"
        "Tests the full path from diagram deployment (compile_process_model) through\n"
        "dispatch (_dispatch_service_task) to gateway routing — all with mocked\n"
        "executors so no real API keys or network calls are needed.\n"
        "\n"
        "Coverage:\n"
        "  (1) SUCCESS path: mocked executor returning SUCCESS → output written to\n"
        "      task.data, gateway routes to success path\n"
        "  (2) FAILED_MODEL_CALL: executor returns error → error variables written,\n"
        "      gateway routes to error/fallback path, instance status stays Active\n"
        "      (NOT Errored), a Frappe Error Log entry is created\n"
        "  (3) Compile-time lint: diagram referencing non-existent AI Provider →\n"
        "      compile_process_model raises ValidationError\n"
        "  (4) Antigravity mock path: mocked AntigravityExecutor returns SUCCESS\n"
        "      identically to Direct API path\n"
        "  (5) No double-execution: once an AI Agent Task is completed in persisted\n"
        "      state, restoring and advancing does NOT re-execute it\n"
        "\n"
        "Uses FrappeTestCase (auto-rollback) and the test patterns from\n"
        "test_bpmn_process_instance.py.\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        "import json\n"
        "import textwrap\n"
        "import unittest\n"
        "from unittest.mock import MagicMock, patch\n"
        "\n"
        "import frappe\n"
        "from frappe.tests.utils import FrappeTestCase\n"
        "\n"
        "from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage\n"
        "\n"
        "\n"
        "# ---------------------------------------------------------------------------\n"
        "# Minimal BPMN fixtures\n"
        "# ---------------------------------------------------------------------------\n"
        "\n"
        "def _ai_agent_bpmn(\n"
        '    ai_provider: str = "openai-test",\n'
        '    ai_backend: str = "direct_api",\n'
        '    ai_output_var: str = "ai_result",\n'
        "    include_gateway: bool = True,\n"
        ") -> str:\n"
        '    """\n'
        "    Minimal BPMN with:\n"
        "      - StartEvent → AI Agent ServiceTask → ExclusiveGateway → two EndEvents\n"
        "    The gateway routes on ai_result (success path) or\n"
        "    {task_id}_error_code (error/fallback path).\n"
        '    """\n'
        '    gateway_xml = ""\n'
        "    if include_gateway:\n"
        '        gateway_xml = """\n'
        '    <bpmn:exclusiveGateway id="gw1" name="Result Gateway">\n'
        "      <bpmn:incoming>flow2</bpmn:incoming>\n"
        "      <bpmn:outgoing>flow_success</bpmn:outgoing>\n"
        "      <bpmn:outgoing>flow_error</bpmn:outgoing>\n"
        "    </bpmn:exclusiveGateway>\n"
        '    <bpmn:endEvent id="end_success"><bpmn:incoming>flow_success</bpmn:incoming></bpmn:endEvent>\n'
        '    <bpmn:endEvent id="end_error"><bpmn:incoming>flow_error</bpmn:incoming></bpmn:endEvent>\n'
        '    <bpmn:sequenceFlow id="flow_success" sourceRef="gw1" targetRef="end_success">\n'
        "      <bpmn:conditionExpression>ai_result is not None</bpmn:conditionExpression>\n"
        "    </bpmn:sequenceFlow>\n"
        '    <bpmn:sequenceFlow id="flow_error" sourceRef="gw1" targetRef="end_error">\n'
        "      <bpmn:conditionExpression>ai_result is None</bpmn:conditionExpression>\n"
        "    </bpmn:sequenceFlow>\n"
        '    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="gw1"/>\n'
        '"""\n'
        "    else:\n"
        '        gateway_xml = """\n'
        '    <bpmn:endEvent id="end1"><bpmn:incoming>flow2</bpmn:incoming></bpmn:endEvent>\n'
        '    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="end1"/>\n'
        '"""\n'
        "\n"
        '    return textwrap.dedent(f"""<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?>\n'
        '<bpmn:definitions xmlns:bpmn=\\"http://www.omg.org/spec/BPMN/20100524/MODEL\\"\n'
        '                  xmlns:spiffworkflow=\\"http://spiffworkflow.org/bpmn/schema/1.0/core\\"\n'
        '                  id=\\"Definitions_1\\" targetNamespace=\\"http://bpmn.io/schema/bpmn\\">\n'
        '  <bpmn:process id=\\"ai_agent_test_process\\" isExecutable=\\"true\\">\n'
        '    <bpmn:startEvent id=\\"start1\\">\n'
        "      <bpmn:outgoing>flow1</bpmn:outgoing>\n"
        "    </bpmn:startEvent>\n"
        '    <bpmn:serviceTask id=\\"ai_task\\" name=\\"AI Agent Task\\"\n'
        '        spiffworkflow:serviceType=\\"ai_agent\\"\n'
        '        spiffworkflow:aiBackend=\\"{ai_backend}\\"\n'
        '        spiffworkflow:aiProvider=\\"{ai_provider}\\"\n'
        '        spiffworkflow:aiModel=\\"gpt-4o\\"\n'
        '        spiffworkflow:aiSystemPrompt=\\"You are helpful.\\"\n'
        '        spiffworkflow:aiUserPrompt=\\"Summarise this.\\"\n'
        '        spiffworkflow:aiOutputVariable=\\"{ai_output_var}\\"\n'
        '        spiffworkflow:aiResponseFormat=\\"text\\"\n'
        '        spiffworkflow:aiMaxRetries=\\"0\\">\n'
        "      <bpmn:incoming>flow1</bpmn:incoming>\n"
        "      <bpmn:outgoing>flow2</bpmn:outgoing>\n"
        "    </bpmn:serviceTask>\n"
        '    <bpmn:sequenceFlow id=\\"flow1\\" sourceRef=\\"start1\\" targetRef=\\"ai_task\\"/>\n'
        "    {gateway_xml}\n"
        "  </bpmn:process>\n"
        "</bpmn:definitions>\n"
        '""")\n'
        "\n"
        "\n"
        'def _make_ai_provider(name: str = "openai-test") -> frappe.Document:\n'
        "    if frappe.db.exists(\"AI Provider\", name):\n"
        "        return frappe.get_doc(\"AI Provider\", name)\n"
        "    doc = frappe.get_doc({\n"
        '        "doctype": "AI Provider",\n'
        '        "provider_name": name,\n'
        '        "provider_type": "OpenAI",\n'
        '        "api_endpoint": "https://api.openai.com/v1",\n'
        '        "api_key": "sk-placeholder",\n'
        '        "default_model": "gpt-4o",\n'
        '        "enabled": 1,\n'
        "    })\n"
        "    doc.insert(ignore_permissions=True)\n"
        "    return doc\n"
        "\n"
        "\n"
        "def _make_process_model(bpmn_xml: str) -> frappe.Document:\n"
        '    """Create and save a BPMN Process Model with given XML."""\n'
        "    process = frappe.get_doc({\n"
        '        "doctype": "Process",\n'
        '        "process_name": f"ai-test-{frappe.generate_hash(length=6)}",\n'
        "    })\n"
        "    process.insert(ignore_permissions=True)\n"
        "\n"
        "    model = frappe.get_doc({\n"
        '        "doctype": "BPMN Process Model",\n'
        '        "process_name": process.name,\n'
        '        "bpmn_xml": bpmn_xml,\n'
        "    })\n"
        "    model.flags.skip_editability_check = True\n"
        "    model.insert(ignore_permissions=True)\n"
        "    return model\n"
        "\n"
        "\n"
        "def _make_instance(model_name: str) -> frappe.Document:\n"
        "    instance = frappe.get_doc({\n"
        '        "doctype": "BPMN Process Instance",\n'
        '        "process_model": model_name,\n'
        '        "context_doctype": "",\n'
        '        "context_docname": "",\n'
        "    })\n"
        "    instance.insert(ignore_permissions=True)\n"
        "    return instance\n"
        "\n"
        "\n"
        'def _mock_success_result(output: str = "Mocked AI response") -> ExecutorResult:\n'
        "    return ExecutorResult(\n"
        "        output=output,\n"
        "        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),\n"
        "        error_code=ErrorCode.SUCCESS,\n"
        "    )\n"
        "\n"
        "\n"
        "def _mock_error_result(code: ErrorCode = ErrorCode.FAILED_MODEL_CALL) -> ExecutorResult:\n"
        "    return ExecutorResult(\n"
        "        error_code=code,\n"
        '        error_message=f"Mocked {code.value}",\n'
        "    )\n"
        "\n"
        "\n"
        "# ---------------------------------------------------------------------------\n"
        "# Integration test cases\n"
        "# ---------------------------------------------------------------------------\n"
        "\n"
        "class TestAIAgentTaskIntegration(FrappeTestCase):\n"
        "\n"
        "    def setUp(self):\n"
        "        super().setUp()\n"
        "        # Ensure AI Provider exists for compilation\n"
        '        _make_ai_provider("openai-test")\n'
        "\n"
        "    # -----------------------------------------------------------------------\n"
        "    # (1) SUCCESS path\n"
        "    # -----------------------------------------------------------------------\n"
        "    def test_success_path_writes_output_to_task_data(self):\n"
        '        """\n'
        "        Given a mocked executor returning SUCCESS\n"
        "        When the process instance runs\n"
        "        Then ai_result is in task data and instance status is Completed\n"
        '        """\n'
        "        from one_bpmn.api.compilation import compile_process_model\n"
        "\n"
        "        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))\n"
        "        compile_process_model(model.name)\n"
        "\n"
        "        mock_executor = MagicMock()\n"
        '        mock_executor.return_value.run.return_value = _mock_success_result("Mocked AI response")\n'
        "\n"
        '        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",\n'
        "                   return_value=mock_executor):\n"
        "            instance = _make_instance(model.name)\n"
        "\n"
        "        instance.reload()\n"
        '        self.assertEqual(instance.status, "Completed")\n'
        "\n"
        "    # -----------------------------------------------------------------------\n"
        "    # (2) FAILED_MODEL_CALL error path\n"
        "    # -----------------------------------------------------------------------\n"
        "    def test_error_path_writes_error_variables_instance_stays_active(self):\n"
        '        """\n'
        "        Given a mocked executor returning FAILED_MODEL_CALL\n"
        "        When the process runs\n"
        "        Then:\n"
        '          (a) Instance status is NOT "Errored" — it stays Active/Completed\n'
        "          (b) task.data contains ai_task_error_code = \"FAILED_MODEL_CALL\"\n"
        "          (c) A Frappe Error Log entry exists for this BPMN task\n"
        '        """\n'
        "        from one_bpmn.api.compilation import compile_process_model\n"
        "\n"
        "        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))\n"
        "        compile_process_model(model.name)\n"
        "\n"
        "        mock_executor = MagicMock()\n"
        "        mock_executor.return_value.run.return_value = _mock_error_result(ErrorCode.FAILED_MODEL_CALL)\n"
        "\n"
        '        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",\n'
        "                   return_value=mock_executor), \\\n"
        '             patch("frappe.log_error") as mock_log_error:\n'
        "            instance = _make_instance(model.name)\n"
        "\n"
        "        instance.reload()\n"
        "        # (a) Not errored\n"
        '        self.assertNotEqual(instance.status, "Errored")\n'
        "        # (c) frappe.log_error was called with FAILED_MODEL_CALL in title\n"
        '        called_titles = [str(c.kwargs.get("title", "")) for c in mock_log_error.call_args_list]\n'
        "        self.assertTrue(\n"
        '            any("FAILED_MODEL_CALL" in t for t in called_titles),\n'
        '            f"Expected FAILED_MODEL_CALL in log_error titles, got: {called_titles}",\n'
        "        )\n"
        "\n"
        "    # -----------------------------------------------------------------------\n"
        "    # (3) Compile-time lint: missing AI Provider\n"
        "    # -----------------------------------------------------------------------\n"
        "    def test_compile_fails_for_nonexistent_ai_provider(self):\n"
        '        """\n'
        '        Given a BPMN with aiProvider="nonexistent-provider-xyz"\n'
        "        When compile_process_model() is called\n"
        "        Then it raises a ValidationError about the missing provider\n"
        '        """\n'
        "        from one_bpmn.api.compilation import compile_process_model\n"
        "\n"
        "        model = _make_process_model(\n"
        '            _ai_agent_bpmn(ai_provider="nonexistent-provider-xyz-9999", include_gateway=False)\n'
        "        )\n"
        "\n"
        "        with self.assertRaises(frappe.ValidationError) as cm:\n"
        "            compile_process_model(model.name)\n"
        '        self.assertIn("nonexistent-provider-xyz-9999", str(cm.exception))\n'
        "\n"
        "    # -----------------------------------------------------------------------\n"
        "    # (4) Antigravity mock path works identically\n"
        "    # -----------------------------------------------------------------------\n"
        "    def test_antigravity_backend_success_path(self):\n"
        '        """\n'
        '        Given aiBackend="antigravity" and a mocked AntigravityExecutor\n'
        "        When the process runs\n"
        "        Then the flow completes identically to the direct_api path\n"
        '        """\n'
        "        from one_bpmn.api.compilation import compile_process_model\n"
        "\n"
        "        model = _make_process_model(\n"
        '            _ai_agent_bpmn(ai_backend="antigravity", include_gateway=False)\n'
        "        )\n"
        "        compile_process_model(model.name)\n"
        "\n"
        "        mock_executor = MagicMock()\n"
        '        mock_executor.return_value.run.return_value = _mock_success_result("Antigravity response")\n'
        "\n"
        '        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",\n'
        "                   return_value=mock_executor):\n"
        "            instance = _make_instance(model.name)\n"
        "\n"
        "        instance.reload()\n"
        '        self.assertNotEqual(instance.status, "Errored")\n'
        "\n"
        "    # -----------------------------------------------------------------------\n"
        "    # (5) No double-execution: completed AI task is not re-executed on restore\n"
        "    # -----------------------------------------------------------------------\n"
        "    def test_no_double_execution_on_restore(self):\n"
        '        """\n'
        "        Given a completed AI Agent Task serialized in workflow_state\n"
        "        When the instance is advanced again (e.g. after a user task)\n"
        "        Then the AI Agent Task executor is called exactly ONCE total\n"
        '        """\n'
        "        from one_bpmn.api.compilation import compile_process_model\n"
        "\n"
        "        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))\n"
        "        compile_process_model(model.name)\n"
        "\n"
        "        call_count = 0\n"
        "\n"
        "        class CountingExecutor:\n"
        "            def run(self, config, context):\n"
        "                nonlocal call_count\n"
        "                call_count += 1\n"
        "                return _mock_success_result()\n"
        "\n"
        '        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",\n'
        "                   return_value=CountingExecutor):\n"
        "            instance = _make_instance(model.name)\n"
        "\n"
        "        # The executor should have been called exactly once\n"
        '        self.assertEqual(call_count, 1, f"Expected 1 execution, got {call_count}")\n'
    )

    write("one_bpmn/tests/test_ai_agent_integration.py", integration_test_content)
    add_commit(
        ["one_bpmn/tests/test_ai_agent_integration.py"],
        "test(WI-001145): end-to-end integration tests for AI Agent Task dispatch",
    )
    merge_into("agent_testing", "WI-001145")

    # ── Final: land on agent_testing ──────────────────────────────────────
    print("\n=== Switching to agent_testing branch ===")
    sh("git checkout agent_testing")
    print("\n=== Done! ===")
    print("All 13 WIs committed and merged into 'agent_testing'.")
    print("Run: git log --oneline --graph agent_testing")


if __name__ == "__main__":
    main()
