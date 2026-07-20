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
import { makeLaunchDocuButton } from "../shared/launchDocuButton";

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
			id: "spiffworkflow-triggerDoctype-launchDocu",
			element,
			component: makeLaunchDocuButton("triggerDoctype"),
		},
		{
			id: "spiffworkflow-triggerType",
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
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "triggerDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
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
	const bo = getBusinessObject(element);

	const getValue = () => getAttr(bo, "triggerType");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
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
