import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h, Component } from "preact";
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


	// Task Actions — always shown
	entries.push({
		id: "spiffworkflow-taskActions",
		element,
		component: TaskActionsTableComponent,
		isEdited: isSelectEntryEdited,
	});

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
		const updates = {
			"spiffworkflow:assigneeMode": value || undefined,
		};

		if (value === "User") {
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
		} else if (value === "DocField") {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
		} else if (value === "Round Robin" || value === "Load Balancing") {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeDocfield"] = undefined;
		} else {
			updates["spiffworkflow:assigneeUser"] = undefined;
			updates["spiffworkflow:assigneeDocfield"] = undefined;
			updates["spiffworkflow:assigneeUsers"] = undefined;
		}

		modeling.updateModdleProperties(element, bo, updates);
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
