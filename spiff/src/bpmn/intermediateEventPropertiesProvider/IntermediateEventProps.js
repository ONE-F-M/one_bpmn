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
const _assignmentCache = new Map(); // doctype → array | undefined
const _assignmentFetching = new Set();

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
			console.error("[IntermediateEvent] fetch DocTypes:", e);
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
			console.error("[IntermediateEvent] fetch Workflows:", e);
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
			console.error("[IntermediateEvent] fetch Workflow States:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_workflowStateCache.set(workflowName, err);
			_workflowStateFetching.delete(workflowName);
			onLoaded(err);
		});
}

function loadAssignmentRules(doctype, onLoaded) {
	if (!doctype) return;
	if (_assignmentCache.has(doctype)) { onLoaded(_assignmentCache.get(doctype)); return; }
	if (_assignmentFetching.has(doctype)) return;
	_assignmentFetching.add(doctype);
	const filters = encodeURIComponent(
		JSON.stringify([
			["document_type", "=", doctype],
			["disabled", "=", 0],
		])
	);
	fetch(
		`/api/resource/Assignment Rule?fields=["name"]&filters=${filters}&limit_page_length=100`,
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			const options = [
				{ label: "-- Select Assignment Rule --", value: "" },
				...data.map((d) => ({ label: d.name, value: d.name })),
			];
			_assignmentCache.set(doctype, options);
			_assignmentFetching.delete(doctype);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[IntermediateEvent] fetch Assignment Rules:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_assignmentCache.set(doctype, err);
			_assignmentFetching.delete(doctype);
			onLoaded(err);
		});
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element, bo) {
	const targetDoctype = bo.get("spiffworkflow:targetDoctype");
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:targetDoctype": targetDoctype,
	});
}

// ---------------------------------------------------------------------------
// Public entry factory
// ---------------------------------------------------------------------------
export function IntermediateEventProps(props) {
	const { element } = props;

	const entries = [
		{
			id: "spiffworkflow-targetDoctype",
			element,
			component: TargetDoctypeComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflow",
			element,
			component: TriggerWorkflowComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflowState",
			element,
			component: TriggerWorkflowStateComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-assignmentRule",
			element,
			component: AssignmentRuleComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	return entries;
}

// ---------------------------------------------------------------------------
// Component 1 — Target DocType
// ---------------------------------------------------------------------------
function TargetDoctypeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	if (!_doctypeCache && !_doctypeFetching) {
		loadDoctypes(() => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "targetDoctype");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype": value || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
			"spiffworkflow:assignmentRule": undefined,
		});
		if (value) {
			loadWorkflows(value, () => touchElement(modeling, element, bo));
			loadAssignmentRules(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		_doctypeCache || [{ label: translate("Loading..."), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Target DocType"),
		getValue,
		setValue,
		getOptions,
	});
}

// ---------------------------------------------------------------------------
// Component 2 — Workflow
// ---------------------------------------------------------------------------
function TriggerWorkflowComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");

	if (doctype && !_workflowCache.has(doctype) && !_workflowFetching.has(doctype)) {
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
// Component 3 — Workflow State
// ---------------------------------------------------------------------------
function TriggerWorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const workflowName = getAttr(bo, "triggerWorkflow");

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

// ---------------------------------------------------------------------------
// Component 4 — Assignment Rule
// ---------------------------------------------------------------------------
function AssignmentRuleComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");

	if (doctype && !_assignmentCache.has(doctype) && !_assignmentFetching.has(doctype)) {
		loadAssignmentRules(doctype, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "assignmentRule");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assignmentRule": value || undefined,
		});
	};

	const getOptions = () =>
		_assignmentCache.get(doctype) ||
		[{ label: doctype ? translate("Loading...") : translate("-- Select DocType first --"), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignment Rule"),
		getValue,
		setValue,
		getOptions,
	});
}
