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
			},
			{
				id: "spiffworkflow-confirmTransition",
				element,
				component: ConfirmTransitionComponent,
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
		// Clear apply_workflow attrs
		const patch = {
			"spiffworkflow:serviceType":          keepServiceType || undefined,
			"spiffworkflow:serviceTargetDoctype": undefined,
			"spiffworkflow:workflowState":        undefined,
			"spiffworkflow:docStatus":            undefined,
			"spiffworkflow:onlyAllowEdit":        undefined,
			"spiffworkflow:confirmTransition":    undefined,
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
		};
		modeling.updateModdleProperties(element, bo, patch);
	};

	const setValue = (value) => clearAll(value);

	const getOptions = () => [
		{ label: translate("-- Select Service Type --"), value: "" },
		{ label: translate("Apply Workflow"),            value: "apply_workflow" },
		{ label: translate("Email Notification"),        value: "send_email" },
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

function ConfirmTransitionComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);

	const checked = getBoolAttr(bo, "confirmTransition");

	const handleChange = (e) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:confirmTransition": e.target.checked ? "true" : undefined,
		});
	};

	return h(
		"div",
		{ class: "bio-properties-panel-entry", "data-entry-id": id },
		h(
			"div",
			{ style: "display:flex;align-items:center;gap:8px;padding:6px 0;" },
			[
				h("input", {
					type: "checkbox",
					id,
					checked,
					onChange: handleChange,
					style: "width:16px;height:16px;cursor:pointer;margin:0;flex-shrink:0;",
				}),
				h(
					"label",
					{
						for: id,
						class: "bio-properties-panel-label",
						style: "margin:0;cursor:pointer;user-select:none;",
					},
					translate("Confirm Transition?")
				),
			]
		)
	);
}

// ===========================================================================
// EMAIL NOTIFICATION COMPONENTS
// ===========================================================================

// ── Divider helper ────────────────────────────────────────────────────────
function SectionDivider({ label }) {
	return h(
		"div",
		{
			style: [
				"font-size:10px",
				"font-weight:700",
				"color:#888",
				"text-transform:uppercase",
				"letter-spacing:0.06em",
				"padding:10px 0 4px 0",
				"border-top:1px solid #e0e0e0",
				"margin-top:6px",
			].join(";"),
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
						class: "bio-properties-panel-input",
						value,
						onInput,
						placeholder,
						rows: 5,
						style: "font-family:monospace;font-size:12px;resize:vertical;",
					})
					: h("input", {
						type: "text",
						id,
						class: "bio-properties-panel-input",
						value,
						onInput,
						placeholder,
					}),
				hint && h("div", { style: "font-size:11px;color:#888;margin-top:3px;line-height:1.4;" }, hint),
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
		h("div", { style: "display:flex;align-items:center;gap:8px;padding:8px 0 4px 0;" }, [
			h("input", {
				type: "checkbox",
				id,
				checked,
				onChange: (e) => modeling.updateModdleProperties(element, bo, {
					"spiffworkflow:emailUseDoctype": e.target.checked ? "true" : undefined,
					"spiffworkflow:emailDoctype":    undefined,
				}),
				style: "width:16px;height:16px;cursor:pointer;margin:0;flex-shrink:0;",
			}),
			h("label", {
				for: id,
				class: "bio-properties-panel-label",
				style: "margin:0;cursor:pointer;user-select:none;font-size:12px;",
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

// ── E6: Document Fields (comma-separated field names that hold email) ─────
function EmailToDocFieldsComponent(props) {
	const { element, id } = props;
	const modeling  = useService("modeling");
	const translate = useService("translate");
	const bo        = getBusinessObject(element);
	const value     = getAttr(bo, "emailToDocFields");

	return h(TextEntry, {
		id,
		label: translate("Document Field"),
		value,
		onInput: (e) => modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:emailToDocFields": e.target.value || undefined,
		}),
		placeholder: translate("e.g. employee_email, manager_email"),
		hint: translate("Comma-separated field names from the context document that contain email addresses."),
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
