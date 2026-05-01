import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { HeaderButton } from "@bpmn-io/properties-panel";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet } from "../shared/frappeResource";

function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

export function ScriptTaskProps(props) {
	const { element } = props;
	return [
		{ id: "spiffworkflow-serverScript", element, component: ServerScriptComponent },
		{ id: "spiffworkflow-launchEditor", element, component: LaunchEditorButton },
	];
}

function ServerScriptComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const currentValue = getAttr(bo, "serverScript");

	const handleSelect = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:serverScript": value || undefined,
		});
		// Also set bpmn:script so linting doesn't complain about empty script
		modeling.updateProperties(element, {
			script: value || undefined,
		});
	};

	// Fetch API-type Server Scripts from Frappe
	const fetchServerScripts = (txt) => {
		const params = {
			fields: '["name"]',
			filters: JSON.stringify([
				["script_type", "=", "API"],
				...(txt ? [["name", "like", `%${txt}%`]] : []),
			]),
			limit_page_length: 50,
			order_by: "name asc",
		};
		return frappeGet("/api/resource/Server Script", params);
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h("label", { class: "bio-properties-panel-label" }, translate("Server Script")),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Select a Frappe Server Script (API type)…"),
				fetchApi: fetchServerScripts,
				valueField: "name",
				renderOption: (opt) => opt.name,
				onChange: handleSelect,
			}),
		])
	);
}

function LaunchEditorButton(props) {
	const { element } = props;
	const eventBus  = useService("eventBus");
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return HeaderButton({
		className: "spiffworkflow-properties-panel-button",
		onClick: () => {
			const currentScript = getAttr(bo, "serverScript") || bo.get("script") || "";
			eventBus.fire("spiff.script.edit", {
				element,
				scriptType: "bpmn:script",
				script: currentScript,
				eventBus,
			});

			// Listen for the dialog response
			eventBus.once("spiff.script.update", (event) => {
				const scriptName = event.script || "";
				// Update spiffworkflow:serverScript (engine reads this)
				modeling.updateModdleProperties(element, bo, {
					"spiffworkflow:serverScript": scriptName || undefined,
				});
				// Also set bpmn:script to satisfy linting
				modeling.updateProperties(element, {
					script: scriptName || undefined,
				});
			});
		},
		children: translate("Launch Editor"),
	});
}
