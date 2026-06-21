import { SelectEntry, isSelectEntryEdited } from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import { frappeGet } from "../shared/frappeResource";
import { FrappeAutocomplete } from "../shared/FrappeAutocomplete";
import { FrappeMultiSelect } from "../shared/FrappeMultiSelect";

// ---------------------------------------------------------------------------
// Document Status options — mirrors Frappe's docstatus values exactly
// ---------------------------------------------------------------------------
const DOC_STATUS_OPTIONS = [
	{ label: "-- Select --", value: "" },
	{ label: "0 (Draft)",     value: "0" },
	{ label: "1 (Submitted)", value: "1" },
	{ label: "2 (Cancelled)", value: "2" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}

function getBoolAttr(bo, attr) {
	const raw = bo.get(`spiffworkflow:${attr}`);
	return raw === true || raw === "true";
}

// ---------------------------------------------------------------------------
// Main entry — builds the entry list shown in the properties panel group
// ---------------------------------------------------------------------------
export function ServiceTaskProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const serviceType = getAttr(bo, "serviceType");

	const entries = [
		{
			id: "spiffworkflow-serviceType",
			element,
			component: ServiceTypeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	// ── Apply Workflow entries ─────────────────────────────────────────────
	if (serviceType === "apply_workflow") {
		entries.push(
			{
				id: "spiffworkflow-serviceTargetDoctype",
				element,
				component: ServiceTargetDoctypeComponent,
				isEdited: isSelectEntryEdited,
			},
			{
				id: "spiffworkflow-workflowState",
				element,
				component: WorkflowStateComponent,
				isEdited: isSelectEntryEdited,
			},
			{
				id: "spiffworkflow-docStatus",
				element,
				component: DocStatusComponent,
				isEdited: isSelectEntryEdited,
			},
			{
				id: "spiffworkflow-onlyAllowEdit",
				element,
				component: OnlyAllowEditComponent,
				isEdited: isSelectEntryEdited,
			}
		);
	}

	// ── Email Notification entries ─────────────────────────────────────────
	if (serviceType === "send_email") {
		entries.push(
			{ id: "spiffworkflow-emailAccount",       element, component: EmailAccountComponent },
			{ id: "spiffworkflow-emailUseDoctype",    element, component: EmailUseDoctypeComponent },
		);
		// Only show Doctype picker when "Based on Specific Doctype" is checked
		if (getBoolAttr(bo, "emailUseDoctype")) {
			entries.push({ id: "spiffworkflow-emailDoctype", element, component: EmailDoctypeComponent });
		}
		entries.push(
			{ id: "spiffworkflow-emailSubject",       element, component: EmailSubjectComponent },
			// ── Recipients section ─────────────────────────────────────────
			{ id: "spiffworkflow-email-recipients-header", element, component: RecipientsHeaderComponent },
			{ id: "spiffworkflow-emailTo",            element, component: EmailToComponent },
			{ id: "spiffworkflow-emailToDocFields",   element, component: EmailToDocFieldsComponent },
			{ id: "spiffworkflow-emailToRoles",       element, component: EmailToRolesComponent },
			// ── CC / BCC ────────────────────────────────────────────────────
			{ id: "spiffworkflow-emailCc",            element, component: EmailCcComponent },
			{ id: "spiffworkflow-emailBcc",           element, component: EmailBccComponent },
			// ── Body ────────────────────────────────────────────────────────
			{ id: "spiffworkflow-emailBody",          element, component: EmailBodyComponent },
		);
	}

	// ── Update Field entries ───────────────────────────────────────────────
	if (serviceType === "update_field") {
		entries.push(
			{ id: "spiffworkflow-updateFieldDoctype",  element, component: UpdateFieldDoctypeComponent },
			{ id: "spiffworkflow-updateFieldRows",     element, component: UpdateFieldRowsComponent },
		);
	}

	// ── Google Chat entries ────────────────────────────────────────────────
	if (serviceType === "google_chat") {
		entries.push(
			{ id: "spiffworkflow-gchatType",    element, component: GchatTypeComponent },
		);
		const gchatType = getAttr(bo, "gchatType");
		if (gchatType === "individual") {
			entries.push({ id: "spiffworkflow-gchatEmail",   element, component: GchatEmailComponent });
		} else if (gchatType === "space") {
			entries.push({ id: "spiffworkflow-gchatSpaceId", element, component: GchatSpaceIdComponent });
		}
		entries.push({ id: "spiffworkflow-gchatMessage", element, component: GchatMessageComponent });
	}

	// ── Push Notification entries ──────────────────────────────────────────
	if (serviceType === "push_notification") {
		entries.push(
			{ id: "spiffworkflow-pushDoctype",             element, component: PushDoctypeComponent },
			{ id: "spiffworkflow-pushTitle",               element, component: PushTitleComponent },
			{ id: "spiffworkflow-push-recipients-header",  element, component: PushRecipientsHeaderComponent },
			{ id: "spiffworkflow-pushToUsers",             element, component: PushToUsersComponent },
			{ id: "spiffworkflow-pushToDocFields",         element, component: PushToDocFieldsComponent },
			{ id: "spiffworkflow-pushToRoles",             element, component: PushToRolesComponent },
			{ id: "spiffworkflow-pushMessage",             element, component: PushMessageComponent },
		);
	}

	return entries;
}

// ===========================================================================
// SERVICE TYPE SELECTOR
// ===========================================================================
function ServiceTypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const getValue = () => getAttr(bo, "serviceType");

	const clearAll = (keepServiceType) => {
		const patch = {
			"spiffworkflow:serviceType":          keepServiceType || undefined,
			// Clear apply_workflow attrs
			"spiffworkflow:serviceTargetDoctype": undefined,
			"spiffworkflow:workflowState":        undefined,
			"spiffworkflow:docStatus":            undefined,
			"spiffworkflow:onlyAllowEdit":        undefined,

			// Clear email attrs
			"spiffworkflow:emailAccount":         undefined,
			"spiffworkflow:emailUseDoctype":      undefined,
			"spiffworkflow:emailDoctype":         undefined,
			"spiffworkflow:emailSubject":         undefined,
			"spiffworkflow:emailTo":              undefined,
			"spiffworkflow:emailToDocFields":     undefined,
			"spiffworkflow:emailToRoles":         undefined,
			"spiffworkflow:emailCc":              undefined,
			"spiffworkflow:emailBcc":             undefined,
			"spiffworkflow:emailBody":            undefined,
			// Clear update_field attrs
			"spiffworkflow:updateFieldDoctype":   undefined,
			"spiffworkflow:updateFieldRows":      undefined,
			"spiffworkflow:updateFieldName":      undefined,
			"spiffworkflow:updateFieldValue":     undefined,
			// Clear google_chat attrs
			"spiffworkflow:gchatType":            undefined,
			"spiffworkflow:gchatEmail":           undefined,
			"spiffworkflow:gchatSpaceId":         undefined,
			"spiffworkflow:gchatMessage":         undefined,
			// Clear push_notification attrs
			"spiffworkflow:pushDoctype":          undefined,
			"spiffworkflow:pushTitle":            undefined,
			"spiffworkflow:pushMessage":          undefined,
			"spiffworkflow:pushToUsers":          undefined,
			"spiffworkflow:pushToDocFields":      undefined,
			"spiffworkflow:pushToRoles":          undefined,
		};
		modeling.updateModdleProperties(element, bo, patch);
	};

	const setValue = (value) => clearAll(value);

	const getOptions = () => [
		{ label: translate("-- Select Service Type --"), value: "" },
		{ label: translate("Apply Workflow"),            value: "apply_workflow" },
		{ label: translate("Email Notification"),        value: "send_email" },
		{ label: translate("Update Field"),              value: "update_field" },
		{ label: translate("Google Chat"),               value: "google_chat" },
		{ label: translate("Push Notification"),         value: "push_notification" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Service Type"),
		getValue,
		setValue,
		getOptions,
	});
}

// ===========================================================================
// APPLY WORKFLOW COMPONENTS (unchanged)
// ===========================================================================
function ServiceTargetDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "serviceTargetDoctype");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:serviceTargetDoctype": val || undefined,
			"spiffworkflow:workflowState":        undefined,
			"spiffworkflow:docStatus":            undefined,
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

function WorkflowStateComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "workflowState");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:workflowState": val || undefined,
		});
	};

	const fetchWorkflowStates = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/Workflow State", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Next Workflow State"),
		value,
		onChange: handleChange,
		fetchApi: fetchWorkflowStates,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

function DocStatusComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const getValue = () => getAttr(bo, "docStatus");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:docStatus": value || undefined,
		});
	};

	const getOptions = () =>
		DOC_STATUS_OPTIONS.map(({ label, value }) => ({
			label: translate(label),
			value,
		}));

	return h(SelectEntry, {
		element,
		id,
		label: translate("Document Status"),
		getValue,
		setValue,
		getOptions,
	});
}

function OnlyAllowEditComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const value = getAttr(bo, "onlyAllowEdit");

	const handleChange = (val) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:onlyAllowEdit": val || undefined,
		});
	};

	const fetchRoles = (txt) => {
		const params = {
			fields: '["name"]',
			limit_page_length: 50,
			order_by: "name asc",
		};
		if (txt) {
			params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		}
		return frappeGet("/api/resource/Role", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Only Allow Edit for"),
		value,
		onChange: handleChange,
		fetchApi: fetchRoles,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}



// ===========================================================================
// EMAIL NOTIFICATION COMPONENTS
// ===========================================================================

// ── Divider helper ────────────────────────────────────────────────────────
function SectionDivider({ label }) {
	return h(
		"div",
		{
			class: "bpmn-section-divider",
		},
		label
	);
}

// ── Inline text/textarea helper ───────────────────────────────────────────
function TextEntry({ id, label, value, onInput, placeholder, multiline, hint }) {
	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ class: multiline ? "bio-properties-panel-textarea" : "bio-properties-panel-textfield" },
			[
				h("label", { class: "bio-properties-panel-label" }, label),
				multiline
					? h("textarea", {
						id,
						class: "bpmn-frappe-textarea",
						value,
						onInput,
						placeholder,
						rows: 5,
					})
					: h("input", {
						type: "text",
						id,
						class: "bio-properties-panel-input",
						value,
						onInput,
						placeholder,
					}),
				hint && h("div", { class: "bpmn-frappe-hint" }, hint),
			]
		)
	);
}

// ── E1: Email Account ─────────────────────────────────────────────────────
function EmailAccountComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailAccount");

	const fetchAccounts = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/Email Account", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Email Account"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailAccount": val || undefined,
		}),
		fetchApi: fetchAccounts,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ── E2: Based on Specific Doctype record (checkbox) ───────────────────────
function EmailUseDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const checked   = getBoolAttr(bo, "emailUseDoctype");

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h("div", { class: "bpmn-checkbox-row" }, [
			h("input", {
				type: "checkbox",
				id,
				checked,
				onChange: (e) => modeling.updateModdleProperties(element, bo, {
					"spiffworkflow:emailUseDoctype": e.target.checked ? "true" : undefined,
					"spiffworkflow:emailDoctype":    undefined,
				}),
				class: "bpmn-checkbox",
			}),
			h("label", {
				for: id,
				class: "bio-properties-panel-label",
				class: "bpmn-checkbox-label-sm",
			}, translate("Based on a Specific Doctype Record")),
		])
	);
}

// ── E3: Doctype (shown when emailUseDoctype=true) ─────────────────────────
function EmailDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailDoctype");

	const fetchDoctypes = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/DocType", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("DocType"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailDoctype": val || undefined,
		}),
		fetchApi: fetchDoctypes,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ── E4: Subject ───────────────────────────────────────────────────────────
function EmailSubjectComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailSubject");

	return h(TextEntry, {
		id,
		label: translate("Subject"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailSubject": e.target.value || undefined,
		}),
		placeholder: translate("e.g. Action Required: {{ doc.name }}"),
		hint: translate("Supports Jinja2 — use {{ doc.field_name }} for document values."),
	});
}

// ── Recipients divider ────────────────────────────────────────────────────
function RecipientsHeaderComponent(props) {
	const { id } = props;
	const translate = useService("translate");
	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(SectionDivider, { label: translate("Recipients") })
	);
}

// ── E5: Email Address (direct comma-separated) ────────────────────────────
function EmailToComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailTo");

	return h(TextEntry, {
		id,
		label: translate("Email Address"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailTo": e.target.value || undefined,
		}),
		placeholder: translate("e.g. john@example.com, jane@example.com"),
		hint: translate("Direct email addresses, comma-separated."),
	});
}

// ── E6: Document Fields (multi-select from DocType fields) ────────────────
function EmailToDocFieldsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailToDocFields");

	// Determine which DocType to fetch fields from:
	// 1. emailDoctype (if "Based on Doctype" is checked)
	// 2. serviceTargetDoctype (if set on this task)
	// 3. Otherwise — we can't dynamically fetch fields
	const sourceDoctype =
		getAttr(bo, "emailDoctype") ||
		getAttr(bo, "serviceTargetDoctype") ||
		"";

	// If no source DocType is known, fall back to plain text input
	if (!sourceDoctype) {
		return h(TextEntry, {
			id,
			label: translate("Document Field"),
			value,
			onInput: (e) => modeling.updateModdleProperties(element, bo, {
				"spiffworkflow:emailToDocFields": e.target.value || undefined,
			}),
			placeholder: translate("e.g. employee_email, manager_email"),
			hint: translate("Set a DocType above to get a field picker. Otherwise, enter comma-separated field names."),
		});
	}

	// Fetch fields from the source DocType that can contain email addresses
	const fetchDocFields = (txt) => {
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype: sourceDoctype,
			search_text: txt || "",
			fieldtype_in: JSON.stringify(["Data", "Link", "Small Text", "Read Only"]),
			include_options: 1,
		});
	};

	return h(FrappeMultiSelect, {
		id,
		label: translate("Document Field"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailToDocFields": val || undefined,
		}),
		fetchApi: fetchDocFields,
		valueField: "fieldname",
		renderOption: (opt) => `${opt.label || opt.fieldname} (${opt.fieldname})`,
		placeholder: translate("Select fields that contain email addresses"),
		itemLabel: "field",
	});
}

// ── E7: Role (comma-separated roles — all users in those roles get email) ─
function EmailToRolesComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailToRoles");

	const fetchRoles = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/Role", params);
	};

	return h(FrappeMultiSelect, {
		id,
		label: translate("Role"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailToRoles": val || undefined,
		}),
		fetchApi: fetchRoles,
		valueField: "name",
		renderOption: (opt) => opt.name,
		placeholder: translate("Select roles — all users in these roles will receive the email"),
		itemLabel: "role",
	});
}

// ── E8: CC ────────────────────────────────────────────────────────────────
function EmailCcComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailCc");

	return h(TextEntry, {
		id,
		label: translate("CC"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailCc": e.target.value || undefined,
		}),
		placeholder: translate("Comma-separated email addresses"),
	});
}

// ── E9: BCC ───────────────────────────────────────────────────────────────
function EmailBccComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailBcc");

	return h(TextEntry, {
		id,
		label: translate("BCC"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailBcc": e.target.value || undefined,
		}),
		placeholder: translate("Comma-separated email addresses"),
	});
}

// ── E10: Email Body (multiline, Jinja-aware) ──────────────────────────────
function EmailBodyComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailBody");

	return h(TextEntry, {
		id,
		label: translate("Email Body"),
		value,
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailBody": e.target.value || undefined,
		}),
		placeholder: translate("Supports Jinja2 — use {{ doc.field_name }}, {{ instance.name }}, etc."),
		hint: translate(
			"HTML or plain text. Available variables: doc (context document), " +
			"instance (BPMN instance), frappe session."
		),
	});
}

// ===========================================================================
// UPDATE FIELD COMPONENTS
// ===========================================================================

// ── UF1: DocType ──────────────────────────────────────────────────────────
function UpdateFieldDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "updateFieldDoctype");

	const fetchDoctypes = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/DocType", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("DocType"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:updateFieldDoctype": val || undefined,
			"spiffworkflow:updateFieldName":    undefined,  // clear field when doctype changes
		}),
		fetchApi: fetchDoctypes,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ── UF2: Field Name (dynamic from selected DocType) ──────────────────────
function UpdateFieldNameComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "updateFieldName");
	const doctype   = getAttr(bo, "updateFieldDoctype");

	if (!doctype) {
		return h(TextEntry, {
			id,
			label: translate("Field"),
			value,
			onInput: (e) => modeling.updateModdleProperties(element, bo, {
				"spiffworkflow:updateFieldName": e.target.value || undefined,
			}),
			placeholder: translate("Select a DocType above first"),
			hint: translate("Select a DocType to get a field picker."),
		});
	}

	const fetchFields = (txt) => {
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype,
			search_text: txt || "",
		});
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Field"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:updateFieldName": val || undefined,
		}),
		fetchApi: fetchFields,
		valueField: "fieldname",
		renderOption: (opt) => `${opt.label || opt.fieldname} (${opt.fieldname}) [${opt.fieldtype}]`,
	});
}

// ── UF3: Value ────────────────────────────────────────────────────────────
function UpdateFieldValueComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "updateFieldValue");

	return h(TextEntry, {
		id,
		label: translate("Value"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:updateFieldValue": e.target.value || undefined,
		}),
		placeholder: translate("e.g. Approved, 1, {{ doc.employee }}"),
		hint: translate(
			"The value to set. Supports Jinja2 templates — use {{ doc.field_name }} " +
			"for dynamic values from the context document."
		),
	});
}


// ===========================================================================
// UPDATE FIELD ROWS COMPONENT
// ===========================================================================

// ── UFR: Multi-row field editor ───────────────────────────────────────────

function UpdateFieldRowsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const doctype   = getAttr(bo, "updateFieldDoctype");

	// Parse stored JSON rows (or migrate legacy single-field)
	let rows = [];
	const stored = getAttr(bo, "updateFieldRows");
	if (stored) {
		try {
			const parsed = JSON.parse(stored);
			if (Array.isArray(parsed)) {
				rows = parsed
					.filter((item) => item && typeof item === "object" && !Array.isArray(item))
					.map((item) => ({ field: item.field || "", value: item.value || "" }));
			}
		} catch(e) {
			rows = [];
		}
	} else {
		const legacyField = getAttr(bo, "updateFieldName");
		const legacyValue = getAttr(bo, "updateFieldValue");
		if (legacyField) rows = [{ field: legacyField, value: legacyValue }];
	}

	const save = (newRows) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:updateFieldRows": newRows.length ? JSON.stringify(newRows) : undefined,
			"spiffworkflow:updateFieldName":  undefined,
			"spiffworkflow:updateFieldValue": undefined,
		});
	};

	const addRow    = ()        => save([...rows, { field: "", value: "" }]);
	const removeRow = (idx)     => save(rows.filter((_, i) => i !== idx));
	const setField  = (idx, v)  => { const r = [...rows]; r[idx] = { ...r[idx], field: v  }; save(r); };
	const setValue  = (idx, v)  => { const r = [...rows]; r[idx] = { ...r[idx], value: v  }; save(r); };

	const fetchFields = (txt) => {
		if (!doctype) return Promise.resolve([]);
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype,
			search_text: txt || "",
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		[
			h("label", { class: "bio-properties-panel-label" }, translate("Field Updates")),
			h(
				"div",
				{ class: "bpmn-field-rows" },
				[
					...rows.map((row, idx) =>
						h("div", { key: idx, class: "bpmn-field-row" }, [
							h(FrappeAutocomplete, {
								id: `${id}-field-${idx}`,
								label: "",
								value: row.field,
								onChange: (v) => setField(idx, v),
								fetchApi: fetchFields,
								valueField: "fieldname",
								renderOption: (opt) => `${opt.label || opt.fieldname} (${opt.fieldname})`,
								placeholder: translate("Field name"),
							}),
							h("input", {
								type: "text",
								class: "bio-properties-panel-input bpmn-field-row-value",
								value: row.value,
								placeholder: translate("Value or {{ doc.field }}"),
								onInput: (e) => setValue(idx, e.target.value),
							}),
							h("button", {
								type: "button",
								class: "bpmn-tag-remove",
								title: translate("Remove row"),
								onClick: () => removeRow(idx),
							}, "×"),
						])
					),
					h("button", {
						type: "button",
						class: "bpmn-add-row-btn",
						onClick: addRow,
					}, `+ ${translate("Add Field")}`),
				]
			),
			h("div", { class: "bio-properties-panel-description" },
				translate("Each row sets one field. Supports Jinja2 in values.")
			),
		]
	);
}

// ===========================================================================
// GOOGLE CHAT COMPONENTS
// ===========================================================================

function GchatTypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const getValue  = () => getAttr(bo, "gchatType");
	const setValue  = (v) => modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:gchatType":    v || undefined,
		"spiffworkflow:gchatEmail":   undefined,
		"spiffworkflow:gchatSpaceId": undefined,
	});
	const getOptions = () => [
		{ label: translate("-- Select --"),  value: "" },
		{ label: translate("Individual (DM)"), value: "individual" },
		{ label: translate("Space"),           value: "space" },
	];

	return h(SelectEntry, { element, id, label: translate("Destination Type"), getValue, setValue, getOptions });
}

function GchatEmailComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(TextEntry, {
		id,
		label: translate("Recipient Email"),
		value: getAttr(bo, "gchatEmail"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:gchatEmail": e.target.value || undefined,
		}),
		placeholder: translate("e.g. john.doe@example.com"),
		hint: translate("Google Workspace email of the DM recipient."),
	});
}

function GchatSpaceIdComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(TextEntry, {
		id,
		label: translate("Space ID"),
		value: getAttr(bo, "gchatSpaceId"),
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:gchatSpaceId": e.target.value || undefined,
		}),
		placeholder: translate("e.g. spaces/AAABBBCCC"),
		hint: translate("Copy from the Google Chat space URL."),
	});
}

function GchatMessageComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	return h(TextEntry, {
		id,
		label: translate("Message"),
		value: getAttr(bo, "gchatMessage"),
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:gchatMessage": e.target.value || undefined,
		}),
		placeholder: translate("e.g. Action required on {{ doc.name }} by {{ doc.owner }}"),
		hint: translate("Supports Jinja2. Variables: doc, instance, frappe."),
	});
}

// ===========================================================================
// PUSH NOTIFICATION COMPONENTS
// ===========================================================================

// ── PN1: Title ────────────────────────────────────────────────────────────
function PushTitleComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushTitle");

	return h(TextEntry, {
		id,
		label: translate("Notification Title"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushTitle": e.target.value || undefined,
		}),
		placeholder: translate("e.g. Action Required: {{ doc.name }}"),
		hint: translate("Supports Jinja2 — use {{ doc.field_name }} for document values."),
	});
}

// ── PN0: Reference DocType ────────────────────────────────────────────────
function PushDoctypeComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushDoctype");

	const fetchDoctypes = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/DocType", params);
	};

	return h(FrappeAutocomplete, {
		id,
		label: translate("Reference DocType"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushDoctype": val || undefined,
			// Clear doc fields selection when DocType changes
			"spiffworkflow:pushToDocFields": undefined,
		}),
		fetchApi: fetchDoctypes,
		valueField: "name",
		renderOption: (opt) => opt.name,
	});
}

// ── PN Recipients divider ─────────────────────────────────────────────────
function PushRecipientsHeaderComponent(props) {
	const { id } = props;
	const translate = useService("translate");
	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(SectionDivider, { label: translate("Recipients") })
	);
}

// ── PN2: Users (multi-select from User doctype) ───────────────────────────
function PushToUsersComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushToUsers");

	const fetchUsers = (txt) => {
		const params = {
			fields: '["name","full_name"]',
			limit_page_length: 50,
			order_by: "full_name asc",
			filters: JSON.stringify([
				["enabled", "=", 1],
				["user_type", "=", "System User"],
			]),
		};
		if (txt) {
			params.or_filters = JSON.stringify([
				["full_name", "like", `%${txt}%`],
				["name", "like", `%${txt}%`],
			]);
		}
		return frappeGet("/api/resource/User", params);
	};

	return h(FrappeMultiSelect, {
		id,
		label: translate("Users"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushToUsers": val || undefined,
		}),
		fetchApi: fetchUsers,
		valueField: "name",
		renderOption: (opt) => `${opt.full_name || opt.name} (${opt.name})`,
		placeholder: translate("Select users to receive push notification"),
		itemLabel: "user",
	});
}

// ── PN3: Document Fields (multi-select from Reference DocType) ────────────
function PushToDocFieldsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushToDocFields");

	// Use the dedicated push notification Reference DocType
	const sourceDoctype = getAttr(bo, "pushDoctype");

	// If no Reference DocType is set, fall back to plain text input
	if (!sourceDoctype) {
		return h(TextEntry, {
			id,
			label: translate("Document Field"),
			value,
			onInput: (e) => modeling.updateModdleProperties(element, bo, {
				"spiffworkflow:pushToDocFields": e.target.value || undefined,
			}),
			placeholder: translate("e.g. owner, custom_manager_user"),
			hint: translate("Set a Reference DocType above to get a field picker."),
		});
	}

	// Fetch user-type fields from the Reference DocType + synthetic Owner entry
	const fetchDocFields = (txt) => {
		return frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
			doctype: sourceDoctype,
			search_text: txt || "",
			fieldtype_in: JSON.stringify(["Link", "Data", "Read Only"]),
			include_options: 1,
		}).then((fields) => {
			// Filter: Link fields must link to User
			let filtered = (fields || []).filter((f) => {
				if (f.fieldtype === "Link") return f.options === "User";
				return true;
			});

			// Prepend synthetic "Owner" field (built-in, not in DocField)
			const ownerEntry = { fieldname: "owner", label: "Owner", fieldtype: "Link", options: "User" };
			const ownerMatch = !txt || "owner".includes(txt.toLowerCase());
			if (ownerMatch) {
				filtered = [ownerEntry, ...filtered];
			}

			return filtered;
		});
	};

	return h(FrappeMultiSelect, {
		id,
		label: translate("Document Field"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushToDocFields": val || undefined,
		}),
		fetchApi: fetchDocFields,
		valueField: "fieldname",
		renderOption: (opt) => `${opt.label || opt.fieldname} (${opt.fieldname})`,
		placeholder: translate("Select fields that contain User IDs"),
		itemLabel: "field",
	});
}

// ── PN4: Roles (multi-select from Role doctype) ──────────────────────────
function PushToRolesComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushToRoles");

	const fetchRoles = (txt) => {
		const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
		if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
		return frappeGet("/api/resource/Role", params);
	};

	return h(FrappeMultiSelect, {
		id,
		label: translate("Role"),
		value,
		onChange: (val) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushToRoles": val || undefined,
		}),
		fetchApi: fetchRoles,
		valueField: "name",
		renderOption: (opt) => opt.name,
		placeholder: translate("Select roles — all users in these roles will receive the notification"),
		itemLabel: "role",
	});
}

// ── PN5: Message (multiline, Jinja-aware, HTML) ──────────────────────────
function PushMessageComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "pushMessage");

	return h(TextEntry, {
		id,
		label: translate("Message Body"),
		value,
		multiline: true,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:pushMessage": e.target.value || undefined,
		}),
		placeholder: translate("Supports Jinja2 — use {{ doc.field_name }}, {{ instance.name }}, etc."),
		hint: translate(
			"HTML or plain text. Available variables: doc (context document), " +
			"instance (BPMN instance), frappe session."
		),
	});
}
