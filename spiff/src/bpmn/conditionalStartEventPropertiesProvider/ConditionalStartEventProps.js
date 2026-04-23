/**
 * ConditionalStartEventProps.js
 *
 * Trigger Configuration entries for Conditional Start Events.
 * Fields:
 *   1. Trigger DocType — searchable autocomplete (Frappe REST API)
 *   2. Trigger Type — "After Insert"
 *
 * All values are persisted as spiffworkflow: extension attributes on the
 * bpmn:ConditionalEventDefinition element so they survive XML round-trips.
 */

import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";

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
		});
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
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Trigger Type --"), value: "" },
		{ label: translate("After Insert"), value: "After Insert" },
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

