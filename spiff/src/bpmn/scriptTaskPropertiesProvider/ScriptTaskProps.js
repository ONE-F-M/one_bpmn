import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet } from "../shared/frappeResource";

function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

export function ScriptTaskProps(props) {
	const { element } = props;
	return [{ id: "spiffworkflow-serverScript", element, component: ServerScriptComponent }];
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
				onChange: handleSelect,  // FrappeAutocomplete calls props.onChange
			}),
			h(
				"div",
				{ class: "bio-properties-panel-description" },
				translate(
					"Select an API-type Server Script. Receives: frappe, doc, context_doctype, " +
					"context_docname, instance. Set result={...} for gateway routing."
				)
			),
		])
	);
}
