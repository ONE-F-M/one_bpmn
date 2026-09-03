import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { FrappeMultiSelect } from "../shared/FrappeMultiSelect";
import { decodeHtmlAttr } from "../shared/htmlAttrCodec";
import { makeLaunchDocuButton } from "../shared/launchDocuButton";

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
			id: "spiffworkflow-targetDoctype-launchDocu",
			element,
			component: makeLaunchDocuButton("targetDoctype"),
		},
		{
			id: "spiffworkflow-assigneeMode",
			element,
			component: AssignmentModeComponent,
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
	} else if (assigneeMode === "Table Field") {
		entries.push({
			id: "spiffworkflow-assigneeTableField",
			element,
			component: AssigneeTableFieldComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-assigneeTableUserField",
			element,
			component: AssigneeTableUserFieldComponent,
			isEdited: isSelectEntryEdited,
		});
	}


	// Task Actions — always shown
	entries.push({
		id: "spiffworkflow-taskActions",
		element,
		component: TaskActionsTableComponent,
		isEdited: isSelectEntryEdited,
	});

	// Notify Assignee — checkbox + conditional Launch Editor button
	entries.push({
		id: "spiffworkflow-notifyAssignee",
		element,
		component: NotifyAssigneeCheckboxComponent,
	});

	if (getAttr(bo, "notifyAssignee") === "true") {
		entries.push({
			id: "spiffworkflow-notifyAssigneeAccount",
			element,
			component: NotifyAssigneeAccountComponent,
		});
		entries.push({
			id: "spiffworkflow-notifyAssigneeEditor",
			element,
			component: NotifyAssigneeEditorButtonComponent,
		});
	}

	return entries;
}

// Notify Assignee — Email Account (which mailbox it is sent FROM)
//
// Mirrors the send_email Service Task's Email Account field, and exists for the
// same reason: a notification moved from a Service Task onto the User Task it
// belongs to must be able to keep sending from the same mailbox. Left empty,
// the site default sender is used.
function NotifyAssigneeAccountComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "notifyAssigneeAccount");

	const fetchAccounts = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/Email Account", params);
	};

	return h(FrappeAutocomplete, {
		id,
		// Deploy rejects Notify Assignee with no account, so the field says so
		// here rather than letting the designer find out at deploy.
		label: translate("Send From (Email Account) — required"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:notifyAssigneeAccount": val || undefined,
		}),
		fetchApi: fetchAccounts,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
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
			// Clear fields that depend on the previous doctype's schema
			"spiffworkflow:assigneeDocfield": undefined,
			"spiffworkflow:assigneeTableField": undefined,
			"spiffworkflow:assigneeTableUserField": undefined,
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
		const updates = {
			"spiffworkflow:assigneeMode": value || undefined,
		};

		if (value === "User") {
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
			updates["spiffworkflow:assigneeTableField"] = undefined;
			updates["spiffworkflow:assigneeTableUserField"] = undefined;
		} else if (value === "DocField") {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
			updates["spiffworkflow:assigneeTableField"] = undefined;
			updates["spiffworkflow:assigneeTableUserField"] = undefined;
		} else if (value === "Round Robin" || value === "Load Balancing") {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeTableField"] = undefined;
			updates["spiffworkflow:assigneeTableUserField"] = undefined;
		} else if (value === "Table Field") {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
		} else {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
			updates["spiffworkflow:assigneeTableField"] = undefined;
			updates["spiffworkflow:assigneeTableUserField"] = undefined;
		}

		modeling.updateModdleProperties(element, bo, updates);
	};

	const getOptions = () => [
		{ label: translate("-- Select Assignment Mode --"), value: "" },
		{ label: translate("User"),            value: "User" },
		{ label: translate("DocField"),        value: "DocField" },
		{ label: translate("Round Robin"),     value: "Round Robin" },
		{ label: translate("Load Balancing"),  value: "Load Balancing" },
		{ label: translate("Table Field"),     value: "Table Field" },
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
		return frappeGet("/api/method/one_bpmn.api.utils.get_assignee_docfields", { doctype })
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

// Component 4b — Table Field (Table MultiSelect field autocomplete, for
// "Table Field" mode). Requires a DocType to be selected above. Any user
// found in any row of this field may complete the task.
function AssigneeTableFieldComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");
	const value   = getAttr(bo, "assigneeTableField");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeTableField": val || undefined,
			// Clear the dependent child-row user field when the table changes
			"spiffworkflow:assigneeTableUserField": undefined,
		});
	};

	const fetchTableFields = (txt) => {
		if (!doctype) {
			return Promise.resolve([
				{ fieldname: "", label: "— Select a DocType first —" },
			]);
		}
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype,
			fieldtype_in: '["Table MultiSelect","Table"]',
			include_options: true,
		}).then((fields) => {
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
		label: translate("Table Field"),
		value,
		onChange: handleChange,
		fetchApi: fetchTableFields,
		valueField: "fieldname",
		renderOption: (opt) =>
			opt.fieldname
				? `${opt.label || opt.fieldname} (${opt.fieldname})`
				: opt.label,
		noResultsText: doctype
			? translate("No Table/Table MultiSelect fields found")
			: translate("Select a DocType first"),
	});
}

// Component 4c — Table Row User Field (Link-to-User field on the child
// doctype referenced by the selected Table Field). Chains two lookups:
// first resolve the child doctype from the parent's table field options,
// then list that child doctype's User-linked fields.
function AssigneeTableUserFieldComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const doctype     = getAttr(bo, "targetDoctype");
	const tableField  = getAttr(bo, "assigneeTableField");
	const value       = getAttr(bo, "assigneeTableUserField");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeTableUserField": val || undefined,
		});
	};

	const fetchChildUserFields = () => {
		if (!doctype || !tableField) {
			return Promise.resolve([
				{ fieldname: "", label: "— Select a Table Field first —" },
			]);
		}
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype,
			fieldtype_in: '["Table MultiSelect","Table"]',
			include_options: true,
		}).then((tableFields) => {
			const match = (Array.isArray(tableFields) ? tableFields : []).find(
				(f) => f.fieldname === tableField
			);
			const childDoctype = match && match.options;
			if (!childDoctype) return [];
			return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
				doctype: childDoctype,
				fieldtype_in: '["Link"]',
				include_options: true,
			}).then((childFields) =>
				(Array.isArray(childFields) ? childFields : []).filter(
					(f) => f.options === "User"
				)
			);
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Row User Field"),
		value,
		onChange: handleChange,
		fetchApi: fetchChildUserFields,
		valueField: "fieldname",
		renderOption: (opt) =>
			opt.fieldname
				? `${opt.label || opt.fieldname} (${opt.fieldname})`
				: opt.label,
		noResultsText: tableField
			? translate("No User-linked fields found on the row doctype")
			: translate("Select a Table Field first"),
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
				itemLabel: "user",
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
				itemLabel: "user",
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

// ─────────────────────────────────────────────────────────────────────────
// Task Actions Child Table — each action is a row with:
//   - Action Name (autocomplete from Workflow Action Master)
//   - Confirm Transition? (checkbox)
//   - Require Digital Signature? (checkbox)
//
// Stored as JSON in spiffworkflow:taskActions:
//   [{"action":"Approve","confirmTransition":"true","requireDigitalSignature":"true"},
//    {"action":"Reject","confirmTransition":"true"}]
//
// Backward-compatible: if the stored value is a plain comma-separated string
// (no leading "["), it is parsed as [{action: "X"}, {action: "Y"}].
// ─────────────────────────────────────────────────────────────────────────

/**
 * Parse the stored taskActions value.
 * Handles both new JSON format and legacy comma-separated strings.
 */
function parseTaskActions(raw) {
	if (!raw) return [];
	const trimmed = raw.trim();
	if (trimmed.startsWith("[")) {
		try {
			const parsed = JSON.parse(trimmed);
			return Array.isArray(parsed) ? parsed : [];
		} catch (_) {
			return [];
		}
	}
	// Legacy: comma-separated action names
	return trimmed
		.split(",")
		.map((a) => a.trim())
		.filter(Boolean)
		.map((action) => ({ action }));
}

/** Serialize actions array back to JSON string for the XML attribute. */
function serializeTaskActions(actions) {
	if (!actions || actions.length === 0) return undefined;
	return JSON.stringify(actions);
}

function TaskActionsTableComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const raw     = getAttr(bo, "taskActions");
	const actions = parseTaskActions(raw);

	// ── Mutate helpers ────────────────────────────────────────────
	const commit = (nextActions) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:taskActions": serializeTaskActions(nextActions),
		});
	};

	const updateRow = (idx, key, value) => {
		const next = actions.map((a, i) =>
			i === idx ? { ...a, [key]: value } : { ...a }
		);
		commit(next);
	};

	const removeRow = (idx) => {
		commit(actions.filter((_, i) => i !== idx));
	};

	const addRow = () => {
		commit([...actions, { action: "" }]);
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: "bio-properties-panel-textfield" },
			[
				h("label", { class: "bio-properties-panel-label" }, translate("Task Actions")),

				h("div", { class: "bpmn-actions-table" }, [
					// ── Column headers ──────────────────────────────
					actions.length > 0 &&
						h("div", { class: "bpmn-actions-table-header" }, [
							h("div", { class: "bpmn-actions-table-header-cell" }, translate("Action")),
							h("div", { class: "bpmn-actions-table-header-cell" }, translate("Confirm")),
							h("div", { class: "bpmn-actions-table-header-cell" }, translate("Sign")),
							h("div", { class: "bpmn-actions-table-header-cell" }),  // remove col
						]),

					// ── Action rows ─────────────────────────────────
					...actions.map((row, idx) =>
						h(ActionRowComponent, {
							key: `action-row-${idx}`,
							row,
							idx,
							element,
							translate,
							onUpdate: updateRow,
							onRemove: removeRow,
						})
					),

					// ── Add button ──────────────────────────────────
					h(
						"button",
						{
							type: "button",
							class: "bpmn-action-add-btn",
							onClick: addRow,
						},
						[
							h("span", {}, "+"),
							h("span", {}, translate("Add Action")),
						]
					),
				]),

				// Description
				h(
					"div",
					{ class: "bio-properties-panel-description" },
					translate(
						"Each action becomes a button visible to the user. " +
						"'Confirm' shows a confirmation dialog before completing. " +
						"'Sign' requires a digital signature before completing. " +
						"The selected action is passed as the 'action' variable — " +
						"use it in Exclusive Gateway conditions (e.g. action == \"Approve\")."
					)
				),
			]
		)
	);
}

/**
 * A single action row with:
 *   - Action name input with autocomplete dropdown
 *   - Confirm Transition checkbox
 *   - Require Digital Signature checkbox
 *   - Remove button
 */
class ActionRowComponent extends Component {
	constructor(props) {
		super(props);
		this.state = {
			inputText: props.row.action || "",
			options: [],
			isOpen: false,
			loading: false,
		};
		this.containerRef  = null;
		this.debounceTimer = null;
		this.handleDocClick = this.handleDocClick.bind(this);
	}

	componentDidMount() {
		document.addEventListener("mousedown", this.handleDocClick);
	}

	componentWillUnmount() {
		document.removeEventListener("mousedown", this.handleDocClick);
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
	}

	handleDocClick(e) {
		if (this.containerRef && !this.containerRef.contains(e.target)) {
			this.setState({ isOpen: false });
		}
	}

	componentDidUpdate(prevProps) {
		// Sync input text when the action name changes externally (undo/redo)
		if (prevProps.row.action !== this.props.row.action) {
			this.setState({ inputText: this.props.row.action || "" });
		}
	}

	fetchOptions(txt) {
		this.setState({ loading: true });
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		frappeGet("/api/resource/Workflow Action Master", params)
			.then((list) => {
				this.setState({ options: list || [], loading: false, isOpen: true });
			})
			.catch(() => this.setState({ loading: false }));
	}

	onInput(e) {
		const val = e.target.value;
		this.setState({ inputText: val });
		if (this.debounceTimer) clearTimeout(this.debounceTimer);
		this.debounceTimer = setTimeout(() => this.fetchOptions(val), 300);
	}

	onFocus() {
		this.fetchOptions(this.state.inputText);
	}

	selectOption(name) {
		this.setState({ inputText: name, isOpen: false });
		this.props.onUpdate(this.props.idx, "action", name);
	}

	onBlur() {
		// If the user typed a manual value, commit it on blur
		setTimeout(() => {
			const { inputText } = this.state;
			if (inputText !== this.props.row.action) {
				this.props.onUpdate(this.props.idx, "action", inputText);
			}
		}, 200);  // delay to allow dropdown click to register first
	}

	render() {
		const { row, idx, translate, onUpdate, onRemove } = this.props;
		const { inputText, options, isOpen, loading } = this.state;

		return h(
			"div",
			{
				class: "bpmn-action-row",
				ref: (c) => (this.containerRef = c),
			},
			[
				// ── Action Name cell ────────────────────────────
				h("div", { class: "bpmn-action-name" }, [
					h("input", {
						type: "text",
						class: "bpmn-action-name-input",
						value: inputText,
						placeholder: translate("Type action…"),
						onInput: (e) => this.onInput(e),
						onFocus: () => this.onFocus(),
						onBlur: () => this.onBlur(),
						autoComplete: "off",
						spellCheck: "false",
					}),
					// Dropdown
					isOpen &&
						h(
							"ul",
							{ class: "bpmn-action-dropdown" },
							[
								loading &&
									h("li", { class: "bpmn-action-dropdown-loading" }, "Loading…"),
								!loading && options.length === 0 &&
									h("li", { class: "bpmn-action-dropdown-empty" }, "No results"),
								!loading &&
									options.map((opt) =>
										h(
											"li",
											{
												key: opt.name,
												onMouseDown: (e) => {
													e.preventDefault();
													this.selectOption(opt.name);
												},
											},
											opt.name
										)
									),
							]
						),
				]),

				// ── Confirm Transition checkbox ─────────────────
				h(
					"div",
					{ class: "bpmn-action-checkbox-cell" },
					h("input", {
						type: "checkbox",
						checked: row.confirmTransition === "true",
						title: translate("Confirm Transition"),
						onChange: (e) =>
							onUpdate(idx, "confirmTransition", e.target.checked ? "true" : undefined),
					})
				),

				// ── Require Digital Signature checkbox ───────────
				h(
					"div",
					{ class: "bpmn-action-checkbox-cell" },
					h("input", {
						type: "checkbox",
						checked: row.requireDigitalSignature === "true",
						title: translate("Require Digital Signature"),
						onChange: (e) =>
							onUpdate(idx, "requireDigitalSignature", e.target.checked ? "true" : undefined),
					})
				),

				// ── Remove button ───────────────────────────────
				h(
					"button",
					{
						type: "button",
						class: "bpmn-action-remove-btn",
						title: translate("Remove action"),
						onClick: () => onRemove(idx),
					},
					"×"
				),
			]
		);
	}
}

// ─────────────────────────────────────────────────────────────────────────
// Notify Assignee — Checkbox + Launch Editor button
// ─────────────────────────────────────────────────────────────────────────

function NotifyAssigneeCheckboxComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const checked = getAttr(bo, "notifyAssignee") === "true";

	const handleChange = (e) => {
		const updates = {
			"spiffworkflow:notifyAssignee": e.target.checked ? "true" : undefined,
		};
		// Clear the body + subject + template when unchecking
		if (!e.target.checked) {
			updates["spiffworkflow:notifyAssigneeBody"] = undefined;
			updates["spiffworkflow:notifyAssigneeSubject"] = undefined;
			updates["spiffworkflow:notifyAssigneeTemplate"] = undefined;
			updates["spiffworkflow:notifyAssigneeAccount"] = undefined;
		}
		modeling.updateModdleProperties(element, bo, updates);
	};

	return h(
		"div",
		{
			class: "bio-properties-panel-entry bpmn-notify-assignee-entry",
			"data-entry-id": id,
		},
		h(
			"div",
			{ class: "bio-properties-panel-textfield" },
			[
				h(
					"label",
					{ class: "bpmn-notify-assignee-label" },
					[
						h("input", {
							type: "checkbox",
							checked,
							onChange: handleChange,
							class: "bpmn-notify-assignee-checkbox",
						}),
						h("span", {}, translate("Notify Assignee")),
					]
				),
				h(
					"div",
					{ class: "bio-properties-panel-description" },
					translate(
						"When enabled, the assigned user receives a notification when this task is created."
					)
				),
			]
		)
	);
}

function NotifyAssigneeEditorButtonComponent(props) {
	const { element, id } = props;
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const eventBus  = useService("eventBus");

	const handleClick = () => {
		eventBus.fire("spiff.userTask.notifyAssignee.edit", {
			element,
			eventBus,
			body: getAttr(bo, "notifyAssigneeBody"),
			subject: getAttr(bo, "notifyAssigneeSubject"),
			template: getAttr(bo, "notifyAssigneeTemplate"),
		});
	};

	const hasBody = !!decodeHtmlAttr(getAttr(bo, "notifyAssigneeBody"));
	const template = getAttr(bo, "notifyAssigneeTemplate");

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		[
			h(
				"button",
				{
					class: "spiffworkflow-properties-panel-button bpmn-notify-editor-btn",
					onClick: handleClick,
					type: "button",
				},
				[
					h("span", {}, translate("Launch Editor")),
					hasBody &&
						h("span", { class: "bpmn-notify-editor-badge" }, "✓"),
				]
			),
			// Template-attached indicator
			h(
				"div",
				{ class: "bio-properties-panel-description bpmn-mt-6" },
				template
					? h("span", {}, `${translate("Template attached")}: ${template}`)
					: h("span", {}, translate("No template attached"))
			),
		]
	);
}
