import {
	HeaderButton,
	SelectEntry,
	isSelectEntryEdited,
	TextFieldEntry,
	isTextFieldEntryEdited,
	TextAreaEntry,
	isTextAreaEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet } from "../shared/frappeResource";

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
		{ id: "selector-aiProvider", element, component: ProviderComponent },
		{
			id: "selector-aiModel",
			element,
			component: ModelComponent,
			isEdited: isTextFieldEntryEdited,
		},
		{
			id: "selector-aiToolSources",
			element,
			component: ToolSourcesComponent,
			isEdited: isSelectEntryEdited,
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

function ProviderComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

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
				value: getAttr(bo, "aiProvider"),
				placeholder: translate("Select an AI Provider…"),
				fetchApi: fetchProviders,
				valueField: "name",
				renderOption: (opt) => opt.provider_name || opt.name,
				onChange: onProviderSelect,
			}),
		])
	);
}

function ModelComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Model"),
		getValue: () => getAttr(bo, "aiModel"),
		setValue: (value) => setAttr(modeling, element, bo, "aiModel", value),
		debounce: useService("debounceInput"),
	});
}

function ToolSourcesComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	return h(SelectEntry, {
		element,
		id,
		label: translate("Tool Sources"),
		description: translate(
			"Where the selector's candidate tools come from: this subprocess's inner tasks, the AI Agent Tool registry, or both."
		),
		getValue: () => getAttr(bo, "aiToolSources") || "both",
		setValue: (value) => setAttr(modeling, element, bo, "aiToolSources", value || "both"),
		getOptions: () => [
			{ value: "both", label: translate("Diagram tasks + registry (default)") },
			{ value: "diagram", label: translate("Diagram tasks only") },
			{ value: "registry", label: translate("Registry tools only") },
		],
	});
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
