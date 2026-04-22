import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
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
			component: TargetDoctypeAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflow",
			element,
			component: WorkflowAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-triggerWorkflowState",
			element,
			component: WorkflowStateAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-assignmentRule",
			element,
			component: AssignmentRuleAutocompleteComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	return entries;
}

// ---------------------------------------------------------------------------
// Component 1 — Target DocType
// ---------------------------------------------------------------------------
function TargetDoctypeAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const value = getAttr(bo, "targetDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype": val || undefined,
			"spiffworkflow:triggerWorkflow": undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
			"spiffworkflow:assignmentRule": undefined,
		});
	};

	const fetchData = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/DocType", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Target DocType"),
		value,
		onChange: handleChange,
		fetchApi: fetchData,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ---------------------------------------------------------------------------
// Component 2 — Workflow
// ---------------------------------------------------------------------------
function WorkflowAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value = getAttr(bo, "triggerWorkflow");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflow": val || undefined,
			"spiffworkflow:triggerWorkflowState": undefined,
		});
	};

	const fetchData = (txt) => {
		if (!doctype) return Promise.resolve([]);
		const filters = [
			["document_type", "=", doctype],
			["is_active", "=", 1],
		];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			filters: JSON.stringify(filters)
		};
		return frappeGet("/api/resource/Workflow", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Workflow"),
		value,
		onChange: handleChange,
		fetchApi: fetchData,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ---------------------------------------------------------------------------
// Component 3 — Workflow State
// ---------------------------------------------------------------------------
function WorkflowStateAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const workflowName = getAttr(bo, "triggerWorkflow");
	const value = getAttr(bo, "triggerWorkflowState");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:triggerWorkflowState": val || undefined,
		});
	};

	const fetchData = (txt) => {
		if (!workflowName) return Promise.resolve([]);
		return frappeGet(`/api/resource/Workflow/${encodeURIComponent(workflowName)}`).then(doc => {
			const states = doc.states || [];
			const txtLower = (txt || "").toLowerCase();
			return states
				.filter(s => s.state.toLowerCase().includes(txtLower))
				.map(s => ({ name: s.state, label: s.state }));
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Workflow State"),
		value,
		onChange: handleChange,
		fetchApi: fetchData,
		valueField: "name",
		renderOption: (opt) => opt.label || opt.name,
	});
}

// ---------------------------------------------------------------------------
// Component 4 — Assignment Rule
// ---------------------------------------------------------------------------
function AssignmentRuleAutocompleteComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value = getAttr(bo, "assignmentRule");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assignmentRule": val || undefined,
		});
	};

	const fetchData = (txt) => {
		if (!doctype) return Promise.resolve([]);
		const filters = [
			["document_type", "=", doctype],
			["disabled", "=", 0],
		];
		if (txt) {
			filters.push(["name", "like", `%${txt}%`]);
		}
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			filters: JSON.stringify(filters)
		};
		return frappeGet("/api/resource/Assignment Rule", params).then(data => 
			Array.isArray(data) ? data : []
		);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Assignment Rule"),
		value,
		onChange: handleChange,
		fetchApi: fetchData,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}
