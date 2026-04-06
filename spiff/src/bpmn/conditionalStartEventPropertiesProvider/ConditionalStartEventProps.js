/**
 * ConditionalStartEventProps.js
 *
 * Trigger Configuration entries for Conditional Start Events.
 * Fields:
 *   1. Trigger DocType — searchable autocomplete (Frappe REST API)
 *   2. Trigger Type — "After Insert" or "Workflow State"
 *   3. Workflow — filtered by selected DocType (visible when type = "Workflow State")
 *   4. Workflow State — filtered by selected Workflow (visible when type = "Workflow State")
 *
 * All values are persisted as spiffworkflow: extension attributes on the
 * bpmn:ConditionalEventDefinition element so they survive XML round-trips.
 */

import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { workflowCache, workflowStateCache, loadWorkflows, loadWorkflowStates } from "../shared/workflowCache";

// ---------------------------------------------------------------------------
// Helpers — read/write on the ConditionalEventDefinition element
// ---------------------------------------------------------------------------
function getConditionalDef(element) {
	const bo = getBusinessObject(element);
	const eventDefs = bo.eventDefinitions || [];
	return eventDefs.find((e) => e.$type === "bpmn:ConditionalEventDefinition");
}

function getAttr(condDef, attr) {
	if (!condDef) return "";
	return condDef.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element) {
	// Force a re-render of the properties panel by doing a no-op property
	// update on the business object. This makes cached async data visible.
	const condDef = getConditionalDef(element);
	if (condDef) {
		const triggerType = condDef.get("spiffworkflow:triggerType");
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerType": triggerType,
		});
	}
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function ConditionalStartEventProps(props) {
	const { element } = props;
	const condDef = getConditionalDef(element);
	if (!condDef) return [];

	const triggerType = getAttr(condDef, "triggerType");

	const entries = [
		{
			id: "spiffworkflow-cond-triggerDoctype",
			element,
			component: TriggerDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-cond-triggerType",
			element,
			component: TriggerTypeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (triggerType === "Workflow State") {
		entries.push({
			id: "spiffworkflow-cond-triggerWorkflow",
			element,
			component: TriggerWorkflowComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-cond-triggerWorkflowState",
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
	const condDef = getConditionalDef(element);

	if (!condDef) return null;

	const value = getAttr(condDef, "triggerDoctype");

	const handleChange = (val) => {
		// Clear dependent fields when doctype changes
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});

		// Pre-load workflows for the new doctype
		if (val) {
			loadWorkflows(val, () => touchElement(modeling, element));
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
	const condDef = getConditionalDef(element);

	if (!condDef) return null;

	const getValue = () => getAttr(condDef, "triggerType");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
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
// Component 3 — Workflow (filtered by doctype)
// ---------------------------------------------------------------------------
function TriggerWorkflowComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const condDef = getConditionalDef(element);

	if (!condDef) return null;

	const doctype = getAttr(condDef, "triggerDoctype");

	if (doctype && !workflowCache.has(doctype)) {
		loadWorkflows(doctype, () => touchElement(modeling, element));
	}

	const getValue = () => getAttr(condDef, "triggerWorkflow");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
			"spiffworkflow:triggerWorkflow": value || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		if (value) {
			loadWorkflowStates(value, () => touchElement(modeling, element));
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
// Component 4 — Workflow State (filtered by workflow)
// ---------------------------------------------------------------------------
function TriggerWorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const condDef = getConditionalDef(element);

	if (!condDef) return null;

	const workflowName = getAttr(condDef, "triggerWorkflow");

	if (workflowName && !workflowStateCache.has(workflowName)) {
		loadWorkflowStates(workflowName, () => touchElement(modeling, element));
	}

	const getValue = () => getAttr(condDef, "triggerWorkflowState");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, condDef, {
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
