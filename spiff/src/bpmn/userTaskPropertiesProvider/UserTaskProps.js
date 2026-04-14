import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { FrappeMultiSelect } from "../shared/FrappeMultiSelect";

// Helpers
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

// Main entry — Assignment Configuration group
export function UserTaskProps(props) {
	const { element } = props;
	const bo           = getBusinessObject(element);
	const assigneeMode = getAttr(bo, "assigneeMode");

	// DocType is always shown (used by DocField, Load Balancing)
	const entries = [
		{
			id: "spiffworkflow-targetDoctype",
			element,
			component: TargetDoctypeComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-assigneeMode",
			element,
			component: AssignmentModeComponent,
			isEdited: isSelectEntryEdited,
		},
		{
			id: "spiffworkflow-taskActionMode",
			element,
			component: TaskActionModeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (assigneeMode === "User") {
		entries.push({
			id: "spiffworkflow-assigneeUser",
			element,
			component: AssigneeUserComponent,
			isEdited: isSelectEntryEdited,
		});
	} else if (assigneeMode === "DocField") {
		entries.push({
			id: "spiffworkflow-assigneeDocfield",
			element,
			component: AssigneeDocfieldComponent,
			isEdited: isSelectEntryEdited,
		});
	} else if (assigneeMode === "Round Robin") {
		entries.push({
			id: "spiffworkflow-assigneeUsers",
			element,
			component: RoundRobinUsersComponent,
		});
	} else if (assigneeMode === "Load Balancing") {
		entries.push({
			id: "spiffworkflow-assigneeUsers",
			element,
			component: LoadBalancingUsersComponent,
		});
	}

	// Task Actions only shown for 'manual' mode
	// (for 'frappe_workflow' mode the actions come live from the context doc)
	const taskActionMode = getAttr(getBusinessObject(element), "taskActionMode") || "manual";
	if (taskActionMode === "manual") {
		entries.push({
			id: "spiffworkflow-taskActions",
			element,
			component: TaskActionsComponent,
			isEdited: isSelectEntryEdited,
		});
	}

	return entries;
}

// Component 1 — DocType (always visible)
// Used by DocField mode (which doctype to look up the user field)
// and by Load Balancing (doctype to count open tasks)
function TargetDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "targetDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype":    val || undefined,
			// Clear the docfield when doctype changes
			"spiffworkflow:assigneeDocfield": undefined,
		});
	};

	const fetchDoctypes = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/DocType", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("DocType"),
		value,
		onChange: handleChange,
		fetchApi: fetchDoctypes,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// Component 2 — Assignment Mode (renamed from Assignee Mode)
// Options: User | DocField | Round Robin | Load Balancing
function AssignmentModeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const getValue = () => getAttr(bo, "assigneeMode");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeMode":     value || undefined,
			// Clear mode-specific fields when mode changes
			"spiffworkflow:assigneeUser":     undefined,
			"spiffworkflow:assigneeDocfield": undefined,
			"spiffworkflow:assigneeUsers":    undefined,
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Assignment Mode --"), value: "" },
		{ label: translate("User"),            value: "User" },
		{ label: translate("DocField"),        value: "DocField" },
		{ label: translate("Round Robin"),     value: "Round Robin" },
		{ label: translate("Load Balancing"),  value: "Load Balancing" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignment Mode"),
		getValue,
		setValue,
		getOptions,
	});
}

// Component 3 — User (single user autocomplete, for "User" mode)
function AssigneeUserComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "assigneeUser");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeUser": val || undefined,
		});
	};

	const fetchUsers = (txt) => {
		const filters = [
			["user_type", "=", "System User"],
			["enabled", "=", 1],
		];
		if (txt) {
			filters.push(["full_name", "like", `%${txt}%`]);
		}
		return frappeGet("/api/resource/User", {
			fields: '["name","full_name"]',
			filters: JSON.stringify(filters),
			limit_page_length: 50,
			order_by: "full_name asc",
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("User"),
		value,
		onChange: handleChange,
		fetchApi: fetchUsers,
		valueField: "name",
		renderOption: (opt) => `${opt.full_name} (${opt.name})`,
	});
}

// Component 4 — DocField (user-linked field autocomplete, for "DocField" mode)
// Requires a DocType to be selected above.
function AssigneeDocfieldComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value   = getAttr(bo, "assigneeDocfield");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeDocfield": val || undefined,
		});
	};

	const fetchDocfields = (txt) => {
		if (!doctype) {
			return Promise.resolve([
				{ fieldname: "", label: "— Select a DocType first —" },
			]);
		}
		return frappeGet("/api/method/one_bpmn.api.get_assignee_docfields", { doctype })
			.then((fields) => {
				const list = Array.isArray(fields) ? fields : [];
				if (!txt) return list;
				const lower = txt.toLowerCase();
				return list.filter(
					(f) =>
						(f.fieldname && f.fieldname.toLowerCase().includes(lower)) ||
						(f.label && f.label.toLowerCase().includes(lower))
				);
			});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("DocField"),
		value,
		onChange: handleChange,
		fetchApi: fetchDocfields,
		valueField: "fieldname",
		renderOption: (opt) =>
			opt.fieldname
				? `${opt.label || opt.fieldname} (${opt.fieldname})`
				: opt.label,
		noResultsText: doctype
			? translate("No User-linked fields found")
			: translate("Select a DocType first"),
	});
}

// Shared helper — fetch users for multi-select
function fetchSystemUsers(txt) {
	const filters = [
		["user_type", "=", "System User"],
		["enabled", "=", 1],
	];
	if (txt) {
		filters.push(["full_name", "like", `%${txt}%`]);
	}
	return frappeGet("/api/resource/User", {
		fields: '["name","full_name"]',
		filters: JSON.stringify(filters),
		limit_page_length: 50,
		order_by: "full_name asc",
	});
}

// Component 5 — Round Robin Users (multi-select + read-only Last Assigned)
// Stores as comma-separated user names in spiffworkflow:assigneeUsers.
// At runtime the engine cycles through the list in order (same as Frappe's
// Assignment Rule "Round Robin" — each new task goes to the next user).
// After each assignment the engine writes spiffworkflow:roundRobinLastUser
// back into the BPMN XML, making it visible here as a read-only field.
function RoundRobinUsersComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value    = getAttr(bo, "assigneeUsers");
	const lastUser = getAttr(bo, "roundRobinLastUser");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeUsers": val || undefined,
		});
	};

	return h(
		"div",
		{},
		[
			h(FrappeMultiSelect, {
				id,
				label: translate("Users (Round Robin)"),
				value,
				onChange: handleChange,
				fetchApi: fetchSystemUsers,
				valueField: "name",
				renderOption: (opt) => `${opt.full_name} (${opt.name})`,
			}),

			// ── Read-only: Last Assigned User ─────────────────────────────────
			h(
				"div",
				{
					class: "bio-properties-panel-entry",
					"data-entry-id": `${id}-last-user`,
					class: "bio-properties-panel-entry bpmn-mt-6",
				},
				h(
					"div",
					{ class: "bio-properties-panel-textfield" },
					[
						h(
							"label",
							{ class: "bio-properties-panel-label" },
							translate("Last Assigned User")
						),
						h("input", {
							type: "text",
							class: "bio-properties-panel-input",
							value: lastUser || translate("Not assigned yet"),
							readOnly: true,
							disabled: true,
							class: "bio-properties-panel-input bpmn-input-readonly",
						}),
					]
				)
			),

			// Helper description
			h(
				"div",
				{
					class: "bio-properties-panel-description",
				},
				translate(
					"Tasks are assigned to each user in turn, cycling through the list. Last Assigned User is updated automatically by the engine after each assignment."
				)
			),
		]
	);
}


// Component 6 — Load Balancing Users (multi-select)
// Stores as comma-separated user names in spiffworkflow:assigneeUsers.
// At runtime the engine assigns to the user with the fewest open tasks
// (same as Frappe's Assignment Rule "Load Balancing"; ties go to first user).
function LoadBalancingUsersComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "assigneeUsers");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeUsers": val || undefined,
		});
	};

	return h(
		"div",
		{},
		[
			h(FrappeMultiSelect, {
				id,
				label: translate("Users (Load Balancing)"),
				value,
				onChange: handleChange,
				fetchApi: fetchSystemUsers,
				valueField: "name",
				renderOption: (opt) => `${opt.full_name} (${opt.name})`,
			}),
			h(
				"div",
				{
					class: "bio-properties-panel-description",
				},
				translate(
					"Assigns to the user with fewest open tasks. On a tie, the first user in the list is chosen (same as Frappe Assignment Rule — Load Balancing)."
				)
			),
		]
	);
}

// Task Actions — define action buttons (e.g. "Approve,Reject,Send Back")
// The chosen label is submitted as {action: "<label>"} when the user clicks
// an action button on the pending task in the instance detail view.
// Exclusive Gateways downstream can route on: action == "Approve"
function TaskActionsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "taskActions");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:taskActions": val || undefined,
		});
	};

	const fetchActions = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/Workflow Action Master", params);
	};

	return h(
		"div",
		{},
		[
			h(FrappeMultiSelect, {
				id,
				label: translate("Task Actions"),
				value,
				onChange: handleChange,
				fetchApi: fetchActions,
				valueField: "name",
				renderOption: (opt) => opt.name,
				placeholder: translate("Search workflow actions…"),
			}),
			h(
				"div",
				{ class: "bio-properties-panel-description" },
				translate(
					"Select actions from Workflow Action Master. " +
					"Each action becomes a button in the Actions menu. " +
					"The selected action is passed as the 'action' variable — " +
					"use it in Exclusive Gateway conditions (e.g. action == \"Approve\")."
				)
			),
		]
	);
}


// Task Action Mode — selects the source of action buttons for this task.
//
//   manual          → designer types comma-separated actions (e.g. "Approve,Reject")
//   frappe_workflow → actions are fetched LIVE at runtime from the context
//                     document's Frappe Workflow transitions rules.
//                     Only transitions the CURRENT USER is allowed to take
//                     (based on role, current state, conditions) are shown —
//                     identical to Frappe's native workflow action panel.
function TaskActionModeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "taskActionMode") || "manual";

	const handleChange = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:taskActionMode": e.target.value || "manual",
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: "bio-properties-panel-select" },
			[
				h("label", { class: "bio-properties-panel-label" }, translate("Task Action Mode")),
				h(
					"select",
					{
						id,
						class: "bio-properties-panel-input",
						value,
						onChange: handleChange,
					},
					[
						h("option", { value: "manual" },   translate("Manual (type actions below)")),
						h("option", { value: "frappe_workflow" }, translate("Frappe Workflow (live from document transitions)")),
					]
				),
				h(
					"div",
					{ class: "bio-properties-panel-description" },
					value === "frappe_workflow"
						? translate(
							"Actions fetched live from the context document's Frappe Workflow. " +
							"Only transitions valid for the current user's role and document state are shown."
						)
						: translate("Type action labels manually below (comma-separated).")
				),
			]
		)
	);
}
