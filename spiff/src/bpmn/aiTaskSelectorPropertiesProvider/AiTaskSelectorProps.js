import {
	HeaderButton,
	TextFieldEntry,
	isTextFieldEntryEdited,
	TextAreaEntry,
	isTextAreaEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet, frappePost } from "../shared/frappeResource";

function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

function setAttr(modeling, element, bo, attr, value) {
	modeling.updateModdleProperties(element, bo, {
		[`spiffworkflow:${attr}`]: value || undefined,
	});
}

export function AiTaskSelectorProps(props) {
	const { element } = props;

	return [
		{ id: "selector-launch", element, component: LaunchSelectorEditorButton },
		{ id: "selector-aiAgentConfig", element, component: AgentConfigComponent },
		{ id: "selector-aiProvider", element, component: ProviderComponent },
		{
			id: "selector-aiModel",
			element,
			component: ModelComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "selector-aiSystemPrompt",
			element,
			component: SystemPromptComponent,
			isEdited: isTextAreaEntryEdited,
		},
		{
			id: "selector-aiUserPrompt",
			element,
			component: UserPromptComponent,
			isEdited: isTextAreaEntryEdited,
		},
	];
}

// Opens the AI Agent config modal in selector mode — same dedicated editor
// (with the AI prompt assistant) used by AI Agent Tasks, restricted to the
// attributes the selector dispatch reads.
function LaunchSelectorEditorButton(props) {
	const { element } = props;
	const eventBus = useService("eventBus");
	const translate = useService("translate");

	return HeaderButton({
		className: "spiffworkflow-properties-panel-button",
		onClick: () => eventBus.fire("launch-ai-agent-editor", { element, mode: "selector" }),
		children: translate("Configure with AI Assistant"),
	});
}

// AI Agent Configuration — seeds the selector's provider/model/prompt/params
// from a saved configuration (one-time copy, editable here). Tools not imported.
function AgentConfigComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

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
						"Optionally link this selector to a saved AI Agent Configuration. At run time the configuration is authoritative for prompt, provider and model; the fields below show its current values. Tools are not imported."
					),
				},
				translate("Linked AI Agent Configuration")
			),
			h(FrappeAutocomplete, {
				value: getAttr(bo, "aiAgentConfig"),
				placeholder: translate("Select a configuration to link…"),
				fetchApi: (txt) =>
					frappeGet("/api/resource/AI Agent Configuration", {
						fields: '["name","agent_id"]',
						filters: JSON.stringify([
							["enabled", "=", 1],
							...(txt ? [["name", "like", `%${txt}%`]] : []),
						]),
						limit_page_length: 50,
						order_by: "name asc",
					}),
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: onConfigSelect,
			}),
			getAttr(bo, "aiAgentConfig")
				? h(
						"div",
						{ class: "bio-properties-panel-description" },
						translate("Linked to: {{config}} — prompt, provider and model resolve from this configuration at run time. The selector dialog's Save writes edits back to it.").replace(
							"{{config}}",
							getAttr(bo, "aiAgentConfig")
						)
				  )
				: null,
		])
	);
}

// WI-001650: read-only. The provider is an agent property, resolved from the
// linked AI Agent Configuration at run time — raw provider setup is retired.
function ProviderComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo = getBusinessObject(element);

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

// WI-001650: read-only — resolved from the linked configuration's credentials.
function ModelComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo = getBusinessObject(element);

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

function SystemPromptComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("System Prompt"),
		getValue: () => getAttr(bo, "aiSystemPrompt"),
		setValue: (value) => setAttr(modeling, element, bo, "aiSystemPrompt", value),
		debounce: useService("debounceInput"),
	});
}

function UserPromptComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	return h(TextAreaEntry, {
		element,
		id,
		label: translate("User Prompt"),
		description: translate(
			"Jinja-rendered with {doc, instance, frappe} — same context as AI Agent Tasks."
		),
		getValue: () => getAttr(bo, "aiUserPrompt"),
		setValue: (value) => setAttr(modeling, element, bo, "aiUserPrompt", value),
		debounce: useService("debounceInput"),
	});
}
