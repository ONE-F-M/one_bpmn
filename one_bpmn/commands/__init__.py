# Copyright (c) 2026, one-fm and contributors
"""Bench commands this app adds. `bench --site <site> <command> --help` for each."""

from one_bpmn.commands.agent_providers import list_agents_without_provider
from one_bpmn.commands.agent_tools import check_agent_tools
from one_bpmn.commands.evals import run_ai_evals

commands = [run_ai_evals, check_agent_tools, list_agents_without_provider]
