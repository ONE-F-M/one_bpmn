import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { HeaderButton } from "@bpmn-io/properties-panel";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { frappeGet } from "../shared/frappeResource";

/**
 * Read a spiffworkflow-namespaced attribute from a business object.
 */
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

/**
 * Entry definitions for the Business Rule Properties group.
 *
 * Returns two entries:
 *   1. DecisionTablePicker — autocomplete dropdown searching by ID and name
 *   2. LaunchEditorButton  — opens the DMN editor dialog
 */
export function BusinessRuleTaskProps(props) {
	const { element } = props;
	return [
		{ id: "spiffworkflow-decisionTable", element, component: DecisionTablePicker },
		{ id: "spiffworkflow-launchDmnEditor", element, component: LaunchDmnEditorButton },
	];
}

/**
 * DecisionTablePicker — autocomplete that searches Workflow Decision Table
 * records stored in the parent BPMN Process Model.
 *
 * Searches by both decision_id and decision_name so the user can type
 * either the BPMN element ID or the human-readable name.
 *
 * When a decision is selected, the decision_id is stored in the
 * spiffworkflow:calledDecisionId extension attribute on the BPMN element.
 */
function DecisionTablePicker(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const currentValue = getAttr(bo, "calledDecisionId");

	const handleSelect = (value, opt) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:calledDecisionId": value || undefined,
		});
	};

	/**
	 * Fetch decisions from the backend.
	 *
	 * Reads the process model name from the Frappe page route
	 * (same pattern used elsewhere in the editor).
	 * Supports filtering by a search term that matches against both
	 * decision_id and decision_name.
	 */
	const fetchDecisions = (txt) => {
		// Resolve the current process model name from the page URL.
		// URL pattern: /processa/process/{processName}/diagram/{modelName}
		const pathParts = window.location.pathname.split("/");
		const diagramIdx = pathParts.indexOf("diagram");
		const modelName = diagramIdx > -1 && pathParts[diagramIdx + 1]
			? decodeURIComponent(pathParts[diagramIdx + 1])
			: null;

		if (!modelName) {
			return Promise.resolve([]);
		}

		const params = {
			process_model: modelName,
		};
		if (txt) {
			params.search_term = txt;
		}

		return frappeGet(
			"/api/method/one_bpmn.api.dmn_api.get_decision_list",
			params
		).then((data) => {
			const list = Array.isArray(data) ? data : [];
			return list;
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bio-properties-panel-textfield" }, [
			h("label", { class: "bio-properties-panel-label" }, translate("Select Decision Table")),
			h(FrappeAutocomplete, {
				value: currentValue,
				placeholder: translate("Search by ID or name…"),
				fetchApi: fetchDecisions,
				valueField: "decision_id",
				renderOption: (opt) => {
					// Show "Name (ID)" format for easy identification
					if (opt.decision_name && opt.decision_name !== opt.decision_id) {
						return `${opt.decision_name} (${opt.decision_id})`;
					}
					return opt.decision_id;
				},
				onChange: handleSelect,
				noResultsText: translate("No decision tables found"),
			}),
			h("div", {
				class: "bio-properties-panel-description",
				style: "font-size: 11px; color: #6b7280; margin-top: 4px;",
			}, translate("Select a decision table from the list")),
		])
	);
}

/**
 * LaunchDmnEditorButton — opens the DMN editor dialog for the selected
 * Business Rule Task. Fires the spiff.dmn.edit event which is already
 * handled by BpmnEditor.vue.
 */
function LaunchDmnEditorButton(props) {
	const { element } = props;
	const eventBus  = useService("eventBus");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return HeaderButton({
		className: "spiffworkflow-properties-panel-button",
		onClick: () => {
			const currentDecision = getAttr(bo, "calledDecisionId") || "";
			eventBus.fire("spiff.dmn.edit", {
				element,
				value: currentDecision,
				eventBus,
			});
		},
		children: translate("Launch Editor"),
	});
}
