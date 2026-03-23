/**
 * StartEventProps.js
 *
 * Trigger Configuration entries for plain Start Events.
 *
 * Design note on async options:
 * @bpmn-io/properties-panel renders SelectEntry using its own bundled Preact.
 * Using preact/hooks (useState, useEffect) from our project leads to a
 * dual-Preact-instance error because the render context lives in the panel's
 * Preact, not ours. We therefore avoid hooks entirely.
 *
 * Instead each async-options component:
 *  1. Reads from a module-level cache synchronously on every render.
 *  2. If the cache is empty, kicks off a fetch and, when the fetch resolves,
 *     touches the element via modeling.updateModdleProperties (a no-op touch)
 *     which causes bpmn-js to re-render the properties panel — at which point
 *     the cache is hot and the real options appear.
 */

import {
	SelectEntry,
	isSelectEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";

// ---------------------------------------------------------------------------
// Module-level async caches (survive across re-renders)
// ---------------------------------------------------------------------------
let _doctypeCache = null; // null = not yet fetched
let _doctypeFetching = false;
const _workflowCache = new Map(); // doctype → array | undefined
const _workflowFetching = new Set();
const _workflowStateCache = new Map(); // workflow → array | undefined
const _workflowStateFetching = new Set();

function loadDoctypes(onLoaded) {
	if (_doctypeCache) { onLoaded(_doctypeCache); return; }
	if (_doctypeFetching) return;
	_doctypeFetching = true;
	fetch(
		"/api/resource/DocType?fields=[\"name\"]&limit_page_length=9999&order_by=name+asc",
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			_doctypeCache = [
				{ label: "-- Select DocType --", value: "" },
				...data.map((d) => ({ label: d.name, value: d.name })),
			];
			_doctypeFetching = false;
			onLoaded(_doctypeCache);
		})
		.catch((e) => {
			console.error("[StartEvent] fetch DocTypes:", e);
			_doctypeCache = [{ label: "-- Error loading --", value: "" }];
			_doctypeFetching = false;
			onLoaded(_doctypeCache);
		});
}

function loadWorkflows(doctype, onLoaded) {
	if (!doctype) return;
	if (_workflowCache.has(doctype)) { onLoaded(_workflowCache.get(doctype)); return; }
	if (_workflowFetching.has(doctype)) return;
	_workflowFetching.add(doctype);
	const filters = encodeURIComponent(
		JSON.stringify([
			["document_type", "=", doctype],
			["is_active", "=", 1],
		])
	);
	fetch(
		`/api/resource/Workflow?fields=["name"]&filters=${filters}&limit_page_length=100`,
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			const options = [
				{ label: "-- Select Workflow --", value: "" },
				...data.map((d) => ({ label: d.name, value: d.name })),
			];
			_workflowCache.set(doctype, options);
			_workflowFetching.delete(doctype);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[StartEvent] fetch Workflows:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowCache.set(doctype, err);
			_workflowFetching.delete(doctype);
			onLoaded(err);
		});
}

function loadWorkflowStates(workflowName, onLoaded) {
	if (!workflowName) return;
	if (_workflowStateCache.has(workflowName)) { onLoaded(_workflowStateCache.get(workflowName)); return; }
	if (_workflowStateFetching.has(workflowName)) return;
	_workflowStateFetching.add(workflowName);
	fetch(`/api/resource/Workflow/${encodeURIComponent(workflowName)}`, {
		credentials: "include",
	})
		.then((r) => r.json())
		.then((json) => {
			const doc = json.data || json.message || {};
			const states = doc.states || [];
			const options = [
				{ label: "-- Select State --", value: "" },
				...states.map((s) => ({ label: s.state, value: s.state })),
			];
			_workflowStateCache.set(workflowName, options);
			_workflowStateFetching.delete(workflowName);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[StartEvent] fetch Workflow States:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowStateCache.set(workflowName, err);
			_workflowStateFetching.delete(workflowName);
			onLoaded(err);
		});
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

/**
 * Touch the element with a no-op update to force a properties panel re-render.
 * This is necessary after an async fetch resolves so the new options are shown.
 */
function touchElement(modeling, element, bo) {
	// We do a real no-op: set the same value back so the panel re-renders.
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
			component: TriggerDoctypeComponent,
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
// Component 1 — Trigger DocType
// ---------------------------------------------------------------------------
function TriggerDoctypeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	// Kick off background fetch; when done, touch element to re-render panel
	if (!_doctypeCache && !_doctypeFetching) {
		loadDoctypes(() => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerDoctype");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerDoctype": value || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		// Pre-warm the workflow cache for the newly selected doctype
		if (value) {
			loadWorkflows(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		_doctypeCache || [{ label: translate("Loading..."), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Trigger DocType"),
		getValue,
		setValue,
		getOptions,
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

	// Kick off fetch if needed
	if (doctype && !_workflowCache.has(doctype) && !_workflowFetching.has(doctype)) {
		loadWorkflows(doctype, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "triggerWorkflow");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflow": value || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
		// Pre-warm state cache
		if (value) {
			loadWorkflowStates(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		_workflowCache.get(doctype) ||
		[{ label: doctype ? translate("Loading...") : translate("-- Select DocType first --"), value: "" }];

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

	// Kick off fetch if needed
	if (
		workflowName &&
		!_workflowStateCache.has(workflowName) &&
		!_workflowStateFetching.has(workflowName)
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
		_workflowStateCache.get(workflowName) ||
		[{ label: workflowName ? translate("Loading...") : translate("-- Select Workflow first --"), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Workflow State"),
		getValue,
		setValue,
		getOptions,
	});
}
