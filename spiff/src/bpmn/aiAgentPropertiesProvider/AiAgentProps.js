import {
	SelectEntry,
	isSelectEntryEdited,
	TextFieldEntry,
	isTextFieldEntryEdited,
	TextAreaEntry,
	isTextAreaEntryEdited,
	HeaderButton,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet, frappePost } from "../shared/frappeResource";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

function setAttr(modeling, element, bo, attr, value) {
	modeling.updateModdleProperties(element, bo, {
		[`spiffworkflow:${attr}`]: value || undefined,
	});
}

// Human-readable labels for the executor backend stored in spiffworkflow:aiBackend.
const BACKEND_LABELS = {
	direct_api: "Direct API",
	antigravity: "Google Antigravity SDK",
};

// A task counts as "configured" once an AI Provider is selected AND the core
// task instruction (the user prompt) has been entered.
function isConfigured(bo) {
	return Boolean(getAttr(bo, "aiProvider")) && Boolean(getAttr(bo, "aiUserPrompt"));
}

// ---------------------------------------------------------------------------
// Entry list — the launcher button followed by the inline config fields,
// rendered the same way as the other service-task property groups.
// ---------------------------------------------------------------------------
export function AiAgentProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);

	const entries = [
		{ id: "ai-agent-launch", element, component: LaunchEditorButton },
		{
			id: "spiffworkflow-aiAgentConfig",
			element,
			component: AgentConfigComponent,
		},
		{
			id: "spiffworkflow-aiProvider",
			element,
			component: ProviderComponent,
		},
		{
			id: "spiffworkflow-aiBackend",
			element,
			component: BackendComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-aiModel",
			element,
			component: ModelComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "spiffworkflow-aiOutputVariable",
			element,
			component: OutputVariableComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "spiffworkflow-aiSystemPrompt",
			element,
			component: SystemPromptComponent,
			isEdited: isTextAreaEntryEdited,
		},
		{
			id: "spiffworkflow-aiUserPrompt",
			element,
			component: UserPromptComponent,
			isEdited: isTextAreaEntryEdited,
		},
		{
			id: "spiffworkflow-aiToolParams",
			element,
			component: ToolParamsComponent,
			isEdited: isTextAreaEntryEdited,
		},
		{
			id: "spiffworkflow-aiToolsAdhoc",
			element,
			component: ToolsAdhocComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "spiffworkflow-aiToolCallResults",
			element,
			component: ToolCallResultsComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "spiffworkflow-aiMaxToolCalls",
			element,
			component: MaxToolCallsComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "spiffworkflow-aiResponseFormat",
			element,
			component: ResponseFormatComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	// Schema field only appears when the response format is JSON.
	if (getAttr(bo, "aiResponseFormat") === "json") {
		entries.push({
			id: "spiffworkflow-aiResponseSchema",
			element,
			component: ResponseSchemaComponent,
			isEdited: isTextAreaEntryEdited,
		});
	}

	return entries;
}

// ---------------------------------------------------------------------------
// Launcher — opens the dedicated modal editor (with the AI assistant).
// Uses the same HeaderButton style as the Script Task "Launch Logix" button.
// ---------------------------------------------------------------------------
function LaunchEditorButton(props) {
	const { element } = props;
	const translate = useService("translate");
	const eventBus  = useService("eventBus");
	const bo        = getBusinessObject(element);

	return HeaderButton({
		className: "spiffworkflow-properties-panel-button ai-agent-launch-btn",
		onClick: () => eventBus.fire("launch-ai-agent-editor", { element }),
		children: isConfigured(bo)
			? translate("Edit AI Task Configuration")
			: translate("Configure AI Task"),
	});
}

// ---------------------------------------------------------------------------
// AI Agent Configuration — optional. Selecting one SEEDS this task's fields
// (provider, model, system prompt, params) as a one-time copy the designer can
// then edit here. Edits stay on the shape; the configuration is never changed
// from the diagram, and its tools are NOT imported — the toolkit is always the
// diagram's own ad-hoc shapes (WI-001637).
// ---------------------------------------------------------------------------
function AgentConfigComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const currentValue = getAttr(bo, "aiAgentConfig");

	const fetchConfigs = (txt) =>
		frappeGet("/api/resource/AI Agent Configuration", {
			fields: '["name","agent_id"]',
			filters: JSON.stringify([
				["enabled", "=", 1],
				...(txt ? [["name", "like", `%${txt}%`]] : []),
			]),
			limit_page_length: 50,
			order_by: "name asc",
		});

	// On select: record the reference, then seed each mapped field into the
	// shape's own attributes (one-time copy — see module note).
	const onConfigSelect = (value) => {
		setAttr(modeling, element, bo, "aiAgentConfig", value);
		if (!value) return;
		frappePost(
			"/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
			{ config_name: value },
		)
			.then((res) => {
				const fields = (res && res.message) || {};
				Object.entries(fields).forEach(([attr, val]) => {
					setAttr(modeling, element, bo, attr, val);
				});
			})
			.catch(() => {});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h(
				"label",
				{
					class: "bio-properties-panel-label",
					title: translate(
						"Optionally link this task to a saved AI Agent Configuration. At run time the configuration is authoritative for prompt, provider, model and params; the fields below show its current values and act as the fallback if it is deleted. Tools are not imported — the toolkit stays this diagram's ad-hoc shapes."
					),
				},
				translate("Linked AI Agent Configuration")
			),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Select a configuration to link…"),
				fetchApi: fetchConfigs,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: onConfigSelect,
			}),
			currentValue
				? h(
						"div",
						{ class: "bio-properties-panel-description" },
						translate("Linked to: {{config}} — prompt, provider, model and params resolve from this configuration at run time. The task dialog's Save writes edits back to it.").replace(
							"{{config}}",
							currentValue
						)
				  )
				: null,
		])
	);
}

// ---------------------------------------------------------------------------
// AI Provider — autocomplete backed by the AI Provider doctype.
// ---------------------------------------------------------------------------
// WI-001650: read-only. The provider is an agent property, resolved from the
// linked AI Agent Configuration at run time — raw provider setup is retired.
function ProviderComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h(
				"label",
				{
					class: "bio-properties-panel-label",
					title: translate(
						"Resolved from the linked AI Agent Configuration at run time. Raw provider setup is retired (WI-001650) — link an agent configuration above to set the provider."
					),
				},
				translate("AI Provider (from linked configuration)")
			),
			h("input", {
				class: "bio-properties-panel-input",
				value: getAttr(bo, "aiProvider") || "",
				disabled: true,
				placeholder: translate("link an agent configuration"),
			}),
		])
	);
}

// ---------------------------------------------------------------------------
// Backend — kept editable (a provider has no backend of its own).
// ---------------------------------------------------------------------------
function BackendComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(SelectEntry, {
		element,
		id,
		label: translate("Backend"),
		getValue: () => getAttr(bo, "aiBackend") || "direct_api",
		setValue: (value) => setAttr(modeling, element, bo, "aiBackend", value),
		getOptions: () => [
			{ value: "direct_api", label: BACKEND_LABELS.direct_api },
			{ value: "antigravity", label: BACKEND_LABELS.antigravity },
		],
		tooltip: translate(
			"How the model request runs: Direct API (a direct HTTP call to the provider) or the Google Antigravity SDK."
		),
	});
}

// ---------------------------------------------------------------------------
// Model override
// ---------------------------------------------------------------------------
// WI-001650: read-only — resolved from the linked configuration's credentials.
function ModelComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h(
				"label",
				{
					class: "bio-properties-panel-label",
					title: translate(
						"Resolved from the linked AI Agent Configuration's credentials (default model) at run time."
					),
				},
				translate("Model (from linked configuration)")
			),
			h("input", {
				class: "bio-properties-panel-input",
				value: getAttr(bo, "aiModel") || "",
				disabled: true,
				placeholder: translate("resolved from the linked agent"),
			}),
		])
	);
}

// ---------------------------------------------------------------------------
// Output variable name
// ---------------------------------------------------------------------------
function OutputVariableComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Output Variable Name"),
		tooltip: translate(
			"Process variable that receives the agent's final answer. Defaults to <taskId>_output when left blank."
		),
		getValue: () => getAttr(bo, "aiOutputVariable"),
		setValue: (value) => setAttr(modeling, element, bo, "aiOutputVariable", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------
function SystemPromptComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("System Prompt"),
		description: translate("Jinja supported: {{ doc }}, {{ instance }}"),
		tooltip: translate(
			"The agent's role and standing instructions, sent as the system prompt. Jinja supported: {{ doc }}, {{ instance }}."
		),
		getValue: () => getAttr(bo, "aiSystemPrompt"),
		setValue: (value) => setAttr(modeling, element, bo, "aiSystemPrompt", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// User prompt
// ---------------------------------------------------------------------------
function UserPromptComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("User Prompt"),
		description: translate("Jinja supported"),
		tooltip: translate(
			"The specific request/input for this run, sent as the user prompt. Jinja supported."
		),
		getValue: () => getAttr(bo, "aiUserPrompt"),
		setValue: (value) => setAttr(modeling, element, bo, "aiUserPrompt", value),
		debounce,
	});
}

// Tool arguments — only relevant when this shape is itself called as a tool.
function ToolParamsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("Tool Arguments"),
		description: translate("JSON Schema — only used when this shape is called as a tool"),
		tooltip: translate(
			'{"properties": {"arg_name": {"type": "string", "description": "..."}}, "required": ["arg_name"]} ' +
			"— the calling agent passes these as arguments, which become Jinja variables in this shape's own User Prompt (e.g. {{ arg_name }}). Leave blank for a zero-argument tool."
		),
		getValue: () => getAttr(bo, "aiToolParams"),
		setValue: (value) => setAttr(modeling, element, bo, "aiToolParams", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// Tools — the referenced ad-hoc sub-process whose shapes are this agent's
// tools (Camunda's "Ad-hoc sub-process ID"). No registry: the shapes are the
// tools, resolved at compile time.
// ---------------------------------------------------------------------------
function ToolsAdhocComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Tools: Ad-hoc sub-process ID"),
		description: translate("Sub-process whose shapes are the agent's tools"),
		tooltip: translate(
			"The id of the ad-hoc sub-process whose shapes the agent may call as tools "
			+ "(Camunda's 'Ad-hoc sub-process ID'). The shapes are the tools — there is no registry. "
			+ "Script/Service tasks run inline; User/Manual tasks are HUMAN tools — calling one "
			+ "suspends the agent until the assigned person completes the task, then the agent "
			+ "resumes with their output."
		),
		getValue: () => getAttr(bo, "aiToolsAdhoc"),
		setValue: (value) => setAttr(modeling, element, bo, "aiToolsAdhoc", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// Tool call results variable
// ---------------------------------------------------------------------------
function ToolCallResultsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Tool Call Results Variable"),
		tooltip: translate(
			"Process variable that collects the results the tool shapes returned "
			+ "(Camunda's 'Tool call results'). Defaults to <taskId>_toolCallResults."
		),
		getValue: () => getAttr(bo, "aiToolCallResults"),
		setValue: (value) => setAttr(modeling, element, bo, "aiToolCallResults", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// Limits — maximum model calls
// ---------------------------------------------------------------------------
function MaxToolCallsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Maximum Model Calls"),
		tooltip: translate(
			"Caps the agent's tool-calling loop (Camunda's 'Limits'). Defaults to 10 when blank."
		),
		getValue: () => getAttr(bo, "aiMaxToolCalls"),
		setValue: (value) => setAttr(modeling, element, bo, "aiMaxToolCalls", value),
		debounce,
	});
}

// ---------------------------------------------------------------------------
// Response format
// ---------------------------------------------------------------------------
function ResponseFormatComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(SelectEntry, {
		element,
		id,
		label: translate("Response Format"),
		getValue: () => getAttr(bo, "aiResponseFormat") || "text",
		setValue: (value) => setAttr(modeling, element, bo, "aiResponseFormat", value),
		getOptions: () => [
			{ value: "text", label: translate("Text") },
			{ value: "json", label: translate("JSON") },
		],
		tooltip: translate(
			"Return the answer as free Text, or as structured JSON validated against a schema."
		),
	});
}

// ---------------------------------------------------------------------------
// Response schema (only when format = JSON)
// ---------------------------------------------------------------------------
function ResponseSchemaComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("Response Schema"),
		description: translate("JSON Schema"),
		tooltip: translate(
			"JSON Schema the response must satisfy. Applies only when Response Format is JSON."
		),
		getValue: () => getAttr(bo, "aiResponseSchema"),
		setValue: (value) => setAttr(modeling, element, bo, "aiResponseSchema", value),
		debounce,
	});
}
