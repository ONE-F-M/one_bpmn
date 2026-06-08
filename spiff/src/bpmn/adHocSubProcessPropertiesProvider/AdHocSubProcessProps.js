import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { FrappeMultiSelect } from "../shared/FrappeMultiSelect";

// Helpers
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

function getBoolAttr(bo, attr) {
	const raw = bo.get(`spiffworkflow:${attr}`);
	return raw === true || raw === "true";
}

// Inline text/textarea helper
function TextEntry({ id, label, value, onInput, placeholder, multiline, hint }) {
	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: multiline ? "bio-properties-panel-textarea" : "bio-properties-panel-textfield" },
			[
				h("label", { class: "bio-properties-panel-label" }, label),
				multiline
					? h("textarea", {
						id,
						class: "bpmn-frappe-textarea",
						value,
						onInput,
						placeholder,
						rows: 5,
					})
					: h("input", {
						type: "text",
						id,
						class: "bio-properties-panel-input",
						value,
						onInput,
						placeholder,
					}),
				hint && h("div", { class: "bpmn-frappe-hint" }, hint),
			]
		)
	);
}

function SectionDivider({ label }) {
	return h(
		"div",
		{
			class: "bpmn-section-divider",
		},
		label
	);
}

export function AdHocSubProcessProps(props) {
	const { element, translate } = props;
	const bo = getBusinessObject(element);
	const serviceType = getAttr(bo, "serviceType");

	const entries = [
		{
			id: "spiffworkflow-isAiAgent",
			element,
			component: IsAiAgentComponent,
		},
	];

	if (serviceType === "ai_agent") {
		const executionMode = getAttr(bo, "aiExecutionMode") || "direct_api";

		// ── Core Configuration (LLM & Execution) ──
		entries.push(
			{ id: "spiffworkflow-ai-core-header", element, component: () => h(SectionDivider, { label: translate("Core Configuration (LLM & Execution)") }) },
			{ id: "spiffworkflow-aiExecutionMode", element, component: AiExecutionModeComponent }
		);

		if (executionMode === "direct_api") {
			entries.push(
				{ id: "spiffworkflow-aiLlmProvider", element, component: AiLlmProviderComponent },
				{ id: "spiffworkflow-aiModelId", element, component: AiModelIdComponent },
				{ id: "spiffworkflow-aiApiEndpoint", element, component: AiApiEndpointComponent },
				{ id: "spiffworkflow-aiApiKeySecret", element, component: AiApiKeySecretComponent },
				{ id: "spiffworkflow-aiTemperature", element, component: AiTemperatureComponent },
				{ id: "spiffworkflow-aiTopP", element, component: AiTopPComponent },
				{ id: "spiffworkflow-aiMaxTokens", element, component: AiMaxTokensComponent },
				{ id: "spiffworkflow-aiTimeout", element, component: AiTimeoutComponent },
				{ id: "spiffworkflow-aiJobWorkerType", element, component: AiJobWorkerTypeComponent }
			);
		} else {
			// antigravity_sdk mode
			entries.push(
				{ id: "spiffworkflow-aiModelId", element, component: AiModelIdComponent },
				{ id: "spiffworkflow-aiResponseSchema", element, component: AiResponseSchemaComponent }
			);
		}

		// ── System Prompts & Memory (Agent Context) ──
		entries.push(
			{ id: "spiffworkflow-ai-prompt-header", element, component: () => h(SectionDivider, { label: translate("System Prompts & Memory (Agent Context)") }) },
			{ id: "spiffworkflow-aiSystemInstructions", element, component: AiSystemInstructionsComponent },
			{ id: "spiffworkflow-aiUserMessage", element, component: AiUserMessageComponent }
		);

		if (executionMode === "direct_api") {
			entries.push(
				{ id: "spiffworkflow-aiContextVariable", element, component: AiContextVariableComponent },
				{ id: "spiffworkflow-aiMaxMessages", element, component: AiMaxMessagesComponent },
				{ id: "spiffworkflow-aiDocumentStorageTtl", element, component: AiDocumentStorageTtlComponent },
				{ id: "spiffworkflow-aiDocumentReferences", element, component: AiDocumentReferencesComponent },
				{ id: "spiffworkflow-aiEventHandlingBehavior", element, component: AiEventHandlingBehaviorComponent }
			);
		} else {
			// antigravity_sdk mode
			entries.push(
				{ id: "spiffworkflow-aiContextVariable", element, component: AiContextVariableComponent }
			);
		}

		// ── Tools & MCP Selection Group (Only relevant for Antigravity SDK mode) ──
		if (executionMode === "antigravity_sdk") {
			entries.push(
				{ id: "spiffworkflow-ai-tools-header", element, component: () => h(SectionDivider, { label: translate("Tools & MCP Selection") }) },
				{ id: "spiffworkflow-aiEnableSubagents", element, component: AiEnableSubagentsComponent },
				{ id: "spiffworkflow-aiEnableCodeExecution", element, component: AiEnableCodeExecutionComponent },
				{ id: "spiffworkflow-aiEnabledTools", element, component: AiEnabledToolsComponent },
				{ id: "spiffworkflow-aiMcpServers", element, component: AiMcpServersComponent },
				{ id: "spiffworkflow-aiWorkspaceBoundary", element, component: AiWorkspaceBoundaryComponent },
				{ id: "spiffworkflow-aiHitlApprovals", element, component: AiHitlApprovalsComponent }
			);
		}
	}

	return entries;
}

function IsAiAgentComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const checked = getAttr(bo, "serviceType") === "ai_agent";

	const handleChange = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:serviceType": e.target.checked ? "ai_agent" : undefined,
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bpmn-checkbox-row" }, [
			h("input", {
				type: "checkbox",
				id,
				checked,
				onChange: handleChange,
				class: "bpmn-checkbox",
			}),
			h("label", {
				for: id,
				class: "bpmn-checkbox-label-sm",
			}, translate("Configure as AI Agent")),
		])
	);
}

function AiExecutionModeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const getValue = () => getAttr(bo, "aiExecutionMode") || "direct_api";
	const setValue = (value) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiExecutionMode": value || undefined });
	const getOptions = () => [
		{ label: translate("Standard LLM API (Direct API)"), value: "direct_api" },
		{ label: translate("Google Antigravity SDK"), value: "antigravity_sdk" },
	];
	return h(SelectEntry, { element, id, label: translate("Execution Mode"), getValue, setValue, getOptions });
}

function AiLlmProviderComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const getValue = () => getAttr(bo, "aiLlmProvider") || "openai";
	const setValue = (value) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiLlmProvider": value || undefined });
	const getOptions = () => [
		{ label: translate("OpenAI"), value: "openai" },
		{ label: translate("Anthropic"), value: "anthropic" },
		{ label: translate("Google Vertex AI"), value: "google" },
		{ label: translate("Amazon Bedrock"), value: "bedrock" },
		{ label: translate("OpenAI Compatible / Ollama"), value: "openai_compatible" },
	];
	return h(SelectEntry, { element, id, label: translate("LLM Provider"), getValue, setValue, getOptions });
}

function AiModelIdComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Model ID"),
		value: getAttr(bo, "aiModelId"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiModelId": e.target.value || undefined }),
		placeholder: translate("e.g. gemini-1.5-flash or gpt-4o"),
	});
}

function AiApiEndpointComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("API Endpoint"),
		value: getAttr(bo, "aiApiEndpoint"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiApiEndpoint": e.target.value || undefined }),
		placeholder: translate("e.g. https://api.openai.com/v1"),
	});
}

function AiApiKeySecretComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Authentication Secret Key Reference"),
		value: getAttr(bo, "aiApiKeySecret"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiApiKeySecret": e.target.value || undefined }),
		placeholder: translate("e.g. {{ secrets.OPENAI_API_KEY }}"),
	});
}

function AiTemperatureComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Temperature"),
		value: getAttr(bo, "aiTemperature"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiTemperature": e.target.value || undefined }),
		placeholder: translate("e.g. 0.7"),
	});
}

function AiTopPComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Top P"),
		value: getAttr(bo, "aiTopP"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiTopP": e.target.value || undefined }),
		placeholder: translate("e.g. 1.0"),
	});
}

function AiMaxTokensComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Max Tokens"),
		value: getAttr(bo, "aiMaxTokens"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiMaxTokens": e.target.value || undefined }),
		placeholder: translate("e.g. 2000"),
	});
}

function AiTimeoutComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Timeout Duration"),
		value: getAttr(bo, "aiTimeout"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiTimeout": e.target.value || undefined }),
		placeholder: translate("e.g. PT180S"),
		hint: translate("ISO-8601 duration string (e.g. PT180S).")
	});
}

function AiJobWorkerTypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Custom Job Worker Type"),
		value: getAttr(bo, "aiJobWorkerType"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiJobWorkerType": e.target.value || undefined }),
		placeholder: translate("io.processa:connector-ai-agent"),
	});
}

function AiResponseSchemaComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Response Schema JSON"),
		value: getAttr(bo, "aiResponseSchema"),
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiResponseSchema": e.target.value || undefined }),
		placeholder: translate("{\n  \"type\": \"object\",\n  \"properties\": {\n    \"result\": { \"type\": \"string\" }\n  }\n}"),
		hint: translate("JSON Schema definition for structured model outputs."),
	});
}


function AiSystemInstructionsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("System Instructions (Persona)"),
		value: getAttr(bo, "aiSystemInstructions"),
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiSystemInstructions": e.target.value || undefined }),
		placeholder: translate("You are a trader auditing algo..."),
		hint: translate("Supports Jinja2/FEEL templates.")
	});
}

function AiUserMessageComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("User Message (Initial Request)"),
		value: getAttr(bo, "aiUserMessage"),
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiUserMessage": e.target.value || undefined }),
		placeholder: translate("Perform a check of the trading volume..."),
		hint: translate("Supports Jinja2/FEEL templates.")
	});
}

function AiContextVariableComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Agent Context Variable"),
		value: getAttr(bo, "aiContextVariable"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiContextVariable": e.target.value || undefined }),
		placeholder: translate("e.g. audit_conversation_history"),
	});
}

function AiMaxMessagesComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Max Messages"),
		value: getAttr(bo, "aiMaxMessages"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiMaxMessages": e.target.value || undefined }),
		placeholder: translate("e.g. 20"),
	});
}

function AiDocumentStorageTtlComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Document Storage TTL"),
		value: getAttr(bo, "aiDocumentStorageTtl"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiDocumentStorageTtl": e.target.value || undefined }),
		placeholder: translate("e.g. P30D"),
	});
}

function AiDocumentReferencesComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Document References"),
		value: getAttr(bo, "aiDocumentReferences"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiDocumentReferences": e.target.value || undefined }),
		placeholder: translate("e.g. {{ doc.attachment_id }}"),
	});
}

function AiEventHandlingBehaviorComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const getValue = () => getAttr(bo, "aiEventHandlingBehavior") || "wait_for_tool_call_results";
	const setValue = (value) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiEventHandlingBehavior": value || undefined });
	const getOptions = () => [
		{ label: translate("Wait for tool call results"), value: "wait_for_tool_call_results" },
		{ label: translate("Cancel tool calls"), value: "cancel_tool_calls" },
	];
	return h(SelectEntry, { element, id, label: translate("Event Handling Behavior"), getValue, setValue, getOptions });
}

function AiEnableSubagentsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const checked = getBoolAttr(bo, "aiEnableSubagents");
	const handleChange = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:aiEnableSubagents": e.target.checked ? "true" : undefined,
		});
	};
	return h("div", { class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bpmn-checkbox-row" }, [
			h("input", { type: "checkbox", id, checked, onChange: handleChange, class: "bpmn-checkbox" }),
			h("label", { for: id, class: "bpmn-checkbox-label-sm" }, translate("Enable Subagents")),
		])
	);
}

function AiEnableCodeExecutionComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const checked = getBoolAttr(bo, "aiEnableCodeExecution");
	const handleChange = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:aiEnableCodeExecution": e.target.checked ? "true" : undefined,
		});
	};
	return h("div", { class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bpmn-checkbox-row" }, [
			h("input", { type: "checkbox", id, checked, onChange: handleChange, class: "bpmn-checkbox" }),
			h("label", { for: id, class: "bpmn-checkbox-label-sm" }, translate("Enable Code Execution")),
		])
	);
}

function AiEnabledToolsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "aiEnabledTools");
	const fetchTools = (txt) => {
		const params = { fields: '["tool_name"]', limit_page_length: 50, order_by: "tool_name asc" };
		if (txt) params.filters = JSON.stringify([["tool_name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/AI Tool", params);
	};
	return h(FrappeMultiSelect, {
		id,
		label: translate("Enabled AI Tools"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:aiEnabledTools": val || undefined,
		}),
		fetchApi: fetchTools,
		valueField: "tool_name",
		renderOption: (opt) => opt.tool_name,
		placeholder: translate("Select enabled tools"),
		itemLabel: "tool",
	});
}

function AiMcpServersComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("MCP Servers JSON Configuration"),
		value: getAttr(bo, "aiMcpServers"),
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiMcpServers": e.target.value || undefined }),
		placeholder: translate('[\n  {\n    "name": "MathServer",\n    "type": "stdio",\n    "command": "python3",\n    "args": ["server.py"]\n  }\n]'),
		hint: translate("Configure MCP stdio and SSE server connections as a JSON array.")
	});
}

function AiWorkspaceBoundaryComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Workspace Safety Boundary"),
		value: getAttr(bo, "aiWorkspaceBoundary"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiWorkspaceBoundary": e.target.value || undefined }),
		placeholder: translate("e.g. /Users/abdullahalmarzouq/Frappe"),
	});
}

function AiHitlApprovalsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	return h(TextEntry, {
		id,
		label: translate("Interactive approvals (HITL)"),
		value: getAttr(bo, "aiHitlApprovals"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, { "spiffworkflow:aiHitlApprovals": e.target.value || undefined }),
		placeholder: translate("e.g. run_command, query_clickhouse"),
		hint: translate("Comma-separated tool names requiring confirmation.")
	});
}
