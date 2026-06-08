# Copyright (c) 2026, Abdullah Almarzouq and contributors
# For license information, please see license.txt

import json
import importlib
import requests
import asyncio
import logging
import frappe
from frappe import _

# Configure logger
logger = logging.getLogger("one_bpmn.ai_executor")
logger.setLevel(logging.INFO)


class DirectApiAgentExecutor:
	"""
	Runs AI Agent execution in Direct LLM API Mode.
	Drives the LLM turn loop by executing BPMN tasks or Python paths as tool calls.
	"""
	def __init__(self, task_config: dict, user_prompt: str, tools_list: list = None, bpmn_task_runner=None):
		self.cfg = task_config
		self.prompt = user_prompt
		self.tools_list = tools_list or []
		self.runner = bpmn_task_runner
		self.history = []

	def execute(self) -> dict:
		"""
		Executes the main ReAct loop synchronously.
		"""
		# Fetch conversation history from variable if exists
		history_var = self.cfg.get("aiContextVariable")
		if history_var and self.runner:
			stored = self.runner.get_variable(history_var)
			if stored and isinstance(stored, list):
				self.history = stored

		self.history.append({"role": "user", "content": self.prompt})
		
		# Define tools schema for the LLM
		llm_tools = self.compile_toolbox_schema()
		system_prompt = self.cfg.get("aiSystemInstructions", "You are a helpful assistant.")
		max_messages = int(self.cfg.get("aiMaxMessages") or 20)

		# Core turn loop
		for turn in range(15):  # Safety limit of 15 turns
			messages = [{"role": "system", "content": system_prompt}] + self.history[-max_messages:]
			
			# Invoke LLM endpoint
			response_data = self.call_llm(messages, llm_tools)
			message = response_data.get("choices", [{}])[0].get("message", {})
			
			self.history.append(message)

			# Handle tool calls
			tool_calls = message.get("tool_calls")
			if not tool_calls:
				# Final answer reached
				final_content = message.get("content", "")
				if history_var and self.runner:
					self.runner.set_variable(history_var, self.history)
				return {"content": final_content, "history": self.history}

			# Execute tool calls and append results
			for tool_call in tool_calls:
				func_name = tool_call["function"]["name"]
				args = json.loads(tool_call["function"]["arguments"] or "{}")
				tool_call_id = tool_call["id"]

				# Execute the tool
				try:
					result = self.execute_tool(func_name, args)
				except Exception as e:
					result = f"Error executing tool: {str(e)}"

				self.history.append({
					"role": "tool",
					"tool_call_id": tool_call_id,
					"name": func_name,
					"content": str(result)
				})

		raise Exception("LLM Agent reached maximum execution turns without completing.")

	def call_llm(self, messages: list, tools: list) -> dict:
		url = self.cfg.get("aiApiEndpoint")
		provider = self.cfg.get("aiLlmProvider", "openai")
		model = self.cfg.get("aiModelId")
		
		# Resolve api key from secrets if referenced
		api_key = self.cfg.get("aiApiKeySecret")
		if api_key and api_key.startswith("{{") and api_key.endswith("}}"):
			secret_name = api_key.replace("{{", "").replace("}}", "").strip().split(".")[-1]
			# Try fetching from frappe secrets or settings
			api_key = frappe.db.get_single_value("Processa Settings", secret_name) or ""
		
		headers = {
			"Content-Type": "application/json"
		}
		if api_key:
			headers["Authorization"] = f"Bearer {api_key}"

		payload = {
			"model": model,
			"messages": messages,
			"temperature": float(self.cfg.get("aiTemperature") or 0.7),
			"top_p": float(self.cfg.get("aiTopP") or 1.0),
		}
		if self.cfg.get("aiMaxTokens"):
			payload["max_tokens"] = int(self.cfg.get("aiMaxTokens"))
		if tools:
			payload["tools"] = tools

		# Post to LLM
		timeout = 60
		timeout_str = self.cfg.get("aiTimeout")
		if timeout_str and timeout_str.startswith("PT"):
			try:
				timeout = int(timeout_str.replace("PT", "").replace("S", ""))
			except ValueError:
				pass

		res = requests.post(url, headers=headers, json=payload, timeout=timeout)
		res.raise_for_status()
		return res.json()

	def compile_toolbox_schema(self) -> list:
		llm_tools = []
		
		# 1. Add database-registered Python tools
		for tool_name in self.tools_list:
			tool_doc = frappe.get_doc("AI Tool", tool_name)
			llm_tools.append({
				"type": "function",
				"function": {
					"name": tool_doc.tool_name,
					"description": tool_doc.description,
					"parameters": {
						"type": "object",
						"properties": {
							"args_json": {
								"type": "string",
								"description": "JSON serialized arguments for the Python tool."
							}
						},
						"required": ["args_json"]
					}
				}
			})

		# 2. Add inner BPMN tasks if in Ad-Hoc sub-process mode
		if self.runner and hasattr(self.runner, "get_adhoc_tools"):
			bpmn_tools = self.runner.get_adhoc_tools()
			for bpmn_tool in bpmn_tools:
				llm_tools.append({
					"type": "function",
					"function": {
						"name": bpmn_tool["id"],
						"description": bpmn_tool["description"],
						"parameters": bpmn_tool["parameters"]
					}
				})

		return llm_tools

	def execute_tool(self, tool_name: str, args: dict) -> str:
		# Check if it is a python-based tool
		if frappe.db.exists("AI Tool", tool_name):
			tool_doc = frappe.get_doc("AI Tool", tool_name)
			parts = tool_doc.python_path.split(".")
			module_path = ".".join(parts[:-1])
			func_name = parts[-1]
			
			module = importlib.import_module(module_path)
			func = getattr(module, func_name)
			
			# Execute Python function (passing args_json or args dict directly)
			if "args_json" in args:
				return func(args["args_json"])
			return func(**args)

		# Check if it is a BPMN-based tool call
		if self.runner and hasattr(self.runner, "run_bpmn_tool"):
			return self.runner.run_bpmn_tool(tool_name, args)

		raise Exception(f"Tool '{tool_name}' not found in registry or active BPMN toolbox.")


class AntigravityAgentExecutor:
	"""
	Runs AI Agent execution in Google Antigravity SDK Mode.
	"""
	def __init__(self, task_config: dict, user_prompt: str, tools_list: list = None, bpmn_task_runner=None):
		self.cfg = task_config
		self.prompt = user_prompt
		self.tools_list = tools_list or []
		self.runner = bpmn_task_runner

	def execute(self) -> dict:
		"""
		Executes the task asynchronously using Google Antigravity SDK inside a sync wrapper.
		"""
		return asyncio.run(self.execute_async())

	async def execute_async(self) -> dict:
		from google.antigravity import Agent, LocalAgentConfig, types
		from google.antigravity.types import TemplatedSystemInstructions, CapabilitiesConfig

		# Resolve tools
		injected_tools = []
		for tool_name in self.tools_list:
			tool_doc = frappe.get_doc("AI Tool", tool_name)
			parts = tool_doc.python_path.split(".")
			module_path = ".".join(parts[:-1])
			func_name = parts[-1]
			
			module = importlib.import_module(module_path)
			func = getattr(module, func_name)
			injected_tools.append(func)

		# Setup configuration properties
		mcp_servers = []
		mcp_config_str = self.cfg.get("aiMcpServers")
		if mcp_config_str:
			try:
				parsed_mcp = json.loads(mcp_config_str)
				for server in parsed_mcp:
					if server.get("type") == "stdio":
						mcp_servers.append(types.McpStdioServer(
							command=server.get("command"),
							args=server.get("args", [])
						))
					elif server.get("type") == "sse":
						mcp_servers.append(types.McpSseServer(
							url=server.get("url"),
							headers=server.get("headers", {})
						))
			except Exception as e:
				logger.error(f"Failed to parse MCP servers JSON configuration: {str(e)}")

		# Safety policies
		policies = []
		workspace = self.cfg.get("aiWorkspaceBoundary")
		if workspace:
			from google.antigravity.hooks import policy
			policies.append(policy.workspace_only(workspaces=[workspace]))

		conversation_id = self.cfg.get("aiContextVariable") or f"bpmn-task-{frappe.generate_hash(length=8)}"

		config = LocalAgentConfig(
			model=self.cfg.get("aiModelId", "gemini-3.5-flash"),
			conversation_id=conversation_id,
			system_instructions=TemplatedSystemInstructions(
				identity=self.cfg.get("aiSystemInstructions", "You are an AI Agent executor.")
			),
			tools=injected_tools,
			capabilities=CapabilitiesConfig(
				enable_subagents=self.cfg.get("aiEnableSubagents") == "true",
			),
			mcp_servers=mcp_servers,
			policies=policies
		)

		try:
			async with Agent(config) as agent:
				response = await agent.chat(self.prompt)
				
				# Wait and accumulate the response text
				response_text = ""
				async for token in response:
					response_text += token

				# Capture observability metrics
				usage = agent.conversation.total_usage
				logger.info(
					f"AGY SDK Task Complete - Prompt: {usage.prompt_token_count}, "
					f"Candidates: {usage.candidates_token_count}, "
					f"Total: {usage.total_token_count}"
				)
				
				# Write history back to process instance variable if needed
				if self.runner and self.cfg.get("aiContextVariable"):
					# Map AGY history to standard JSON serialization
					messages_json = []
					for msg in agent.conversation.messages:
						messages_json.append({"role": msg.role, "content": msg.content})
					self.runner.set_variable(self.cfg.get("aiContextVariable"), messages_json)

				return {"content": response_text}

		except Exception as err:
			logger.error(f"Antigravity SDK execution error: {str(err)}")
			raise err
