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
import { frappeGet } from "../shared/frappeResource";

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
		className: "spiffworkflow-properties-panel-button",
		onClick: () => eventBus.fire("launch-ai-agent-editor", { element }),
		children: isConfigured(bo)
			? translate("Edit AI Task Configuration")
			: translate("Configure AI Task"),
	});
}

// ---------------------------------------------------------------------------
// AI Provider — autocomplete backed by the AI Provider doctype (enabled only).
// ---------------------------------------------------------------------------
function ProviderComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const currentValue = getAttr(bo, "aiProvider");

	const fetchProviders = (txt) => {
		const params = {
			fields: '["name","provider_name","default_model"]',
			filters: JSON.stringify([
				["enabled", "=", 1],
				...(txt ? [["provider_name", "like", `%${txt}%`]] : []),
			]),
			limit_page_length: 50,
			order_by: "provider_name asc",
		};
		return frappeGet("/api/resource/AI Provider", params);
	};

	// On provider change, auto-fill the Model from the provider's default_model
	// — same behaviour as the dedicated editor modal (onProviderChange).
	const onProviderSelect = (value) => {
		setAttr(modeling, element, bo, "aiProvider", value);
		if (!value) return;
		frappeGet("/api/resource/AI Provider", {
			filters: JSON.stringify([["name", "=", value]]),
			fields: '["default_model"]',
			limit_page_length: 1,
		})
			.then((rows) => {
				const defaultModel = Array.isArray(rows) && rows[0] ? rows[0].default_model : "";
				if (defaultModel) {
					setAttr(modeling, element, bo, "aiModel", defaultModel);
				}
			})
			.catch(() => {});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h("label", { class: "bio-properties-panel-label" }, translate("AI Provider")),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Select an AI Provider…"),
				fetchApi: fetchProviders,
				valueField: "name",
				renderOption: (opt) => opt.provider_name || opt.name,
				onChange: onProviderSelect,
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
	});
}

// ---------------------------------------------------------------------------
// Model override
// ---------------------------------------------------------------------------
function ModelComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const debounce  = useService("debounceInput");
	const bo        = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Model"),
		description: translate("Overrides the provider's default model"),
		getValue: () => getAttr(bo, "aiModel"),
		setValue: (value) => setAttr(modeling, element, bo, "aiModel", value),
		debounce,
	});
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
		getValue: () => getAttr(bo, "aiUserPrompt"),
		setValue: (value) => setAttr(modeling, element, bo, "aiUserPrompt", value),
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
		getValue: () => getAttr(bo, "aiResponseSchema"),
		setValue: (value) => setAttr(modeling, element, bo, "aiResponseSchema", value),
		debounce,
	});
}
