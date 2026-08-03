"""run_sync must carry the Frappe context into its worker thread.

A stage tool calls ``run_sync(adapter.complete(..., tools=[...]))`` from inside
the agent loop's coroutine, so a loop is already running and the work goes to a
second thread. ``frappe.local`` is a ContextVar-backed werkzeug Local, so
without an explicit context copy that thread has no site, no ``frappe.db`` and
no session, and every frappe call inside the coroutine raises
"RuntimeError: object is not bound".

That failure is invisible from the outside: a sub-agent's read tools catch their
own exceptions and hand the LLM an empty result, so the model silently goes
blind to the live schema. These tests pin the context propagation so it cannot
regress into that state again.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_run_sync_context
"""

from __future__ import annotations

import asyncio
import threading

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import run_sync


def _read_the_database():
    """A frappe call of the kind every agent read tool makes."""
    return frappe.get_all("DocType", limit=1, pluck="name")


class TestRunSyncContext(FrappeTestCase):
    def test_direct_call_has_context(self):
        """No loop running → asyncio.run in this thread. The baseline."""

        async def coro():
            return _read_the_database()

        self.assertTrue(run_sync(coro()))

    def test_nested_call_has_context(self):
        """A loop IS running → worker thread. This is the real agent path."""

        async def outer():
            async def inner():
                return _read_the_database()

            return run_sync(inner())

        self.assertTrue(asyncio.run(outer()))

    def test_nested_call_really_runs_on_another_thread(self):
        """Guard the premise: if this ever stops being a different thread the
        context copy is moot, and the test above would pass for the wrong reason."""
        main = threading.get_ident()

        async def outer():
            async def inner():
                return threading.get_ident()

            return run_sync(inner())

        self.assertNotEqual(asyncio.run(outer()), main)

    def test_nested_call_sees_the_same_site_user_and_connection(self):
        """The thread must share the caller's context, not build a new one — one
        transaction, one connection, same session."""
        expected = (frappe.local.site, frappe.session.user, id(frappe.local.db))

        async def outer():
            async def inner():
                return (frappe.local.site, frappe.session.user, id(frappe.local.db))

            return run_sync(inner())

        self.assertEqual(asyncio.run(outer()), expected)

    def test_nested_call_sees_uncommitted_writes_of_the_caller(self):
        """Same transaction: a row the caller has not committed is visible."""
        note = frappe.get_doc({"doctype": "Note", "title": f"run_sync probe {frappe.generate_hash(length=6)}"})
        note.insert(ignore_permissions=True)
        self.addCleanup(lambda: frappe.db.exists("Note", note.name) and frappe.delete_doc(
            "Note", note.name, force=True, ignore_permissions=True))

        async def outer():
            async def inner():
                return frappe.db.exists("Note", note.name)

            return run_sync(inner())

        self.assertTrue(asyncio.run(outer()), "worker thread is on a different transaction")

    def test_exceptions_still_propagate(self):
        async def outer():
            async def inner():
                raise ValueError("boom")

            return run_sync(inner())

        with self.assertRaises(ValueError):
            asyncio.run(outer())

    def test_agent_read_tools_return_real_data_when_nested(self):
        """End of the chain: the tools the maps hand to their sub-agents."""
        import json

        # Two tools that every affected map has in common, so this test is
        # independent of where the Docu-specific tools live.
        from one_bpmn.tools.tool_for_server_scripts import (
            get_doctype_fields,
            list_api_server_scripts,
        )

        async def outer():
            async def inner():
                return {
                    "get_doctype_fields": json.loads(get_doctype_fields("ToDo")),
                    "list_api_server_scripts": json.loads(list_api_server_scripts()),
                }

            return run_sync(inner())

        got = asyncio.run(outer())
        # each of these degrades to an empty/error payload when the context is lost
        self.assertTrue(got["get_doctype_fields"], "get_doctype_fields went blind")
        self.assertNotIn("error", got["get_doctype_fields"], "get_doctype_fields went blind")
        self.assertTrue(got["list_api_server_scripts"], "list_api_server_scripts went blind")


class TestDirectApiExecutorContext(FrappeTestCase):
    """The executor's own fallback carries the same contract."""

    def test_run_coro_blocking_propagates_context(self):
        from one_bpmn.agents.executor.direct_api import _run_coro_blocking

        async def outer():
            async def inner():
                return _read_the_database()

            return _run_coro_blocking(inner())

        self.assertTrue(asyncio.run(outer()))
