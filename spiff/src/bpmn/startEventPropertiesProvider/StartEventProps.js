/**
 * StartEventProps.js
 *
 * Trigger Configuration entries for plain Start Events.
 */

import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { workflowCache, workflowStateCache, loadWorkflows, loadWorkflowStates } from "../shared/workflowCache";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element, bo) {
	const triggerType = bo.get("spiffworkflow:triggerType");
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:triggerType": triggerType,
	});
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function StartEventProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const triggerType = getAttr(bo, "triggerType");

	const entries = [
		{
			id: "spiffworkflow-triggerDoctype",
			element,
			component: TriggerDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerType",
			element,
			component: TriggerTypeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (triggerType === "Workflow State") {
		entries.push({
			id: "spiffworkflow-triggerWorkflow",
			element,
			component: TriggerWorkflowComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-triggerWorkflowState",
			element,
			component: TriggerWorkflowStateComponent,
			isEdited: isSelectEntryEdited,
		});
	}

	return entries;
}

// ---------------------------------------------------------------------------
// Component 1 — Trigger DocType (Searchable Autocomplete)
// ---------------------------------------------------------------------------
function TriggerDoctypeAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "triggerDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});

		if (val) {
			loadWorkflows(val, () => touchElement(modeling, element, bo));
		}
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Trigger DocType"),
		value,
		onChange: handleChange,
		noResultsText: "No DocTypes found",
	});
}

// ---------------------------------------------------------------------------
// Component 2 — Trigger Type
// ---------------------------------------------------------------------------
function TriggerTypeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const getValue = () => getAttr(bo, "triggerType");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerType": value || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Trigger Type --"), value: "" },
		{ label: translate("After Insert"), value: "After Insert" },
		{ label: translate("Workflow State"), value: "Workflow State" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Trigger Type"),
		getValue,
		setValue,
		getOptions,
	});
}

// ---------------------------------------------------------------------------
// Component 3 — Workflow
// ---------------------------------------------------------------------------
function TriggerWorkflowComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "triggerDoctype");

	if (doctype && !workflowCache.has(doctype)) {
		loadWorkflows(doctype, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerWorkflow");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflow": value || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		if (value) {
			loadWorkflowStates(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		workflowCache.get(doctype) || [
			{
				label: doctype ? translate("Loading...") : translate("-- Select DocType first --"),
				value: "",
			},
		];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Workflow"),
		getValue,
		setValue,
		getOptions,
	});
}

// ---------------------------------------------------------------------------
// Component 4 — Workflow State
// ---------------------------------------------------------------------------
function TriggerWorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const workflowName = getAttr(bo, "triggerWorkflow");

	if (
		workflowName &&
		!workflowStateCache.has(workflowName)
	) {
		loadWorkflowStates(workflowName, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerWorkflowState");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflowState": value || undefined,
		});
	};

	const getOptions = () =>
		workflowStateCache.get(workflowName) || [
			{
				label: workflowName ? translate("Loading...") : translate("-- Select Workflow first --"),
				value: "",
			},
		];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Workflow State"),
		getValue,
		setValue,
		getOptions,
	});
}
