# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Agent2Agent (A2A) protocol implementation for Processa.

A2A is just another authenticated door into ``invoke_agent`` — not a
separate runtime. This package holds the pieces that door is made of:

- ``principal``: service-user provisioning for approved A2A Clients
  (the caller's identity — never the agent's).
- ``card``: the Agent Card builder — generated fresh from AI Agent
  Configuration on every request, never stored.

Wire schemas and error codes live in ``one_bpmn.agents.a2a_contract``.
"""
