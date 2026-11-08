// Field types - mirrors ALLOWED_FIELDTYPES in security/doctype_validator.py.
export const FIELD_TYPES = [
	"Data",
	"Small Text",
	"Text",
	"Long Text",
	"Text Editor",
	"Code",
	"Markdown Editor",
	"Int",
	"Float",
	"Currency",
	"Percent",
	"Check",
	"Date",
	"Datetime",
	"Time",
	"Duration",
	"Select",
	"Link",
	"Dynamic Link",
	"Table",
	"Table MultiSelect",
	"Attach",
	"Attach Image",
	"Signature",
	"Color",
	"Rating",
	"Phone",
	"Password",
	"Read Only",
	"HTML",
	"Heading",
];
// Structural breaks are the layout delimiters of the field list (validator's
// _LAYOUT_FIELDTYPES). They carry no fieldname. HTML/Heading are content fields
// that live inside a column, so they are NOT structural.
export const STRUCTURAL = new Set(["Section Break", "Column Break", "Tab Break"]);
// Types the properties-panel dropdown offers (structure is managed via the
// add-section/column/tab buttons + drag, exactly like Frappe's builder).
export const CONTENT_TYPES = FIELD_TYPES.filter((t) => !STRUCTURAL.has(t));
// Field boolean flags coerced to 0/1 on the way to the backend. Every 'check'
// property surfaced in the field-properties panel must live here so it is a
// controlled boolean in the UI and serialises to 0/1 for Frappe.
export const FIELD_FLAGS = [
	"reqd",
	"in_list_view",
	"unique",
	"read_only",
	"in_standard_filter",
	"hidden",
	"bold",
	"non_negative",
	"collapsible",
	"fetch_if_empty",
	"in_global_search",
	"in_preview",
	"allow_in_quick_entry",
	"translatable",
	"print_hide",
	"report_hide",
	"search_index",
	"ignore_user_permissions",
	"allow_on_submit",
	"set_only_once",
	"allow_bulk_edit",
	"remember_last_selected_value",
	"ignore_xss_filter",
	"in_filter",
	"no_copy",
	"print_hide_if_no_value",
	"hide_days",
	"hide_seconds",
	"is_virtual",
	"sort_options",
	"show_on_timeline",
	"make_attachment_public",
];

// Which control preview to render for a field type (mirrors Frappe's controls).
const _TEXTAREA_TYPES = new Set([
	"Text",
	"Small Text",
	"Long Text",
	"Text Editor",
	"Code",
	"Markdown Editor",
]);
export function previewKind(t) {
	if (t === "Check") return "check";
	if (t === "Select") return "select";
	if (t === "Table" || t === "Table MultiSelect") return "table";
	if (t === "Heading") return "heading";
	if (t === "HTML") return "html";
	if (_TEXTAREA_TYPES.has(t)) return "textarea";
	return "input";
}
export function previewPlaceholder(df) {
	const t = df.fieldtype;
	if (t === "Link" || t === "Dynamic Link") return df.options || "";
	if (t === "Date") return "YYYY-MM-DD";
	if (t === "Datetime") return "YYYY-MM-DD HH:MM:SS";
	if (t === "Time") return "HH:MM:SS";
	if (t === "Currency" || t === "Float" || t === "Int" || t === "Percent") return "0";
	if (t === "Phone") return "+0 000 000 0000";
	if (t === "Attach" || t === "Attach Image") return "Attach a file…";
	if (t === "Color") return "Choose a color";
	return "";
}

export function capitalize(s) {
	return s ? s[0].toUpperCase() + s.slice(1) : s;
}
function optionsHint(t) {
	if (t === "Link" || t === "Table" || t === "Table MultiSelect") return "Target DocType";
	if (t === "Dynamic Link") return "fieldname holding DocType";
	if (t === "Select") return "one choice per line";
	return "—";
}

const _NUMBER_TYPES = new Set(["Int", "Float", "Currency", "Percent"]);
const _NON_NEG_TYPES = new Set(["Int", "Float", "Currency"]);
const _LENGTH_TYPES = new Set([
	"Data",
	"Link",
	"Dynamic Link",
	"Password",
	"Select",
	"Read Only",
	"Attach",
	"Attach Image",
	"Int",
]);
const _GLOBAL_SEARCH_TYPES = new Set([
	"Data",
	"Select",
	"Table",
	"Text",
	"Text Editor",
	"Link",
	"Small Text",
	"Long Text",
	"Read Only",
	"Heading",
	"Dynamic Link",
]);
const _TRANSLATABLE_TYPES = new Set(["Data", "Select", "Text", "Small Text", "Text Editor"]);
const _NO_FETCH_TYPES = new Set(["HTML", "Heading", "Table", "Table MultiSelect"]);
const _PRECISION_OPTS = ["", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

// The full property list Frappe's DocField exposes (order, control type, labels,
// and per-fieldtype visibility mirror frappe/core/doctype/docfield). Layout-only
// props (collapsible, hide_border, show_dashboard…) are omitted since this panel
// only ever edits a real field inside a column.
export function fieldPropDefs(df) {
	const t = df.fieldtype;
	return [
		{ key: "label", label: "Label", type: "data" },
		{ key: "fieldtype", label: "Type", type: "select", options: CONTENT_TYPES },
		{ key: "fieldname", label: "Name", type: "data", mono: true, placeholder: "snake_case" },
		{ key: "reqd", label: "Mandatory", type: "check", show: t !== "Check" && t !== "HTML" },
		{
			key: "precision",
			label: "Precision",
			type: "select",
			options: _PRECISION_OPTS,
			show: t === "Float" || t === "Currency" || t === "Percent",
			hint: "Set non-standard precision for a Float or Currency field.",
		},
		{ key: "length", label: "Length", type: "int", show: _LENGTH_TYPES.has(t) },
		{ key: "search_index", label: "Index", type: "check" },
		{ key: "in_list_view", label: "In List View", type: "check", show: !df.is_virtual },
		{ key: "in_standard_filter", label: "In List Filter", type: "check" },
		{
			key: "in_global_search",
			label: "In Global Search",
			type: "check",
			show: _GLOBAL_SEARCH_TYPES.has(t),
		},
		{
			key: "in_preview",
			label: "In Preview",
			type: "check",
			show: t !== "Table" && t !== "Table MultiSelect",
		},
		{ key: "allow_in_quick_entry", label: "Allow in Quick Entry", type: "check" },
		{ key: "bold", label: "Bold", type: "check" },
		{
			key: "translatable",
			label: "Translatable",
			type: "check",
			show: _TRANSLATABLE_TYPES.has(t),
		},
		{
			key: "options",
			label: "Options",
			type: "textarea",
			placeholder: optionsHint(t),
			hint: "For Links, enter the DocType as range. For Select, enter list of Options, each on a new line.",
		},
		{ key: "default", label: "Default", type: "textarea" },
		{
			key: "fetch_from",
			label: "Fetch From",
			type: "textarea",
			mono: true,
			show: !_NO_FETCH_TYPES.has(t),
			placeholder: "link_field.source_field",
		},
		{
			key: "fetch_if_empty",
			label: "Fetch on Save if Empty",
			type: "check",
			show: !_NO_FETCH_TYPES.has(t),
			hint: "If unchecked, the value will always be re-fetched on save.",
		},
		{
			key: "depends_on",
			label: "Display Depends On (JS)",
			type: "code",
			mono: true,
			placeholder: "eval:doc.status=='Open'",
		},
		{ key: "hidden", label: "Hidden", type: "check" },
		{ key: "read_only", label: "Read Only", type: "check" },
		{ key: "unique", label: "Unique", type: "check" },
		{ key: "set_only_once", label: "Set only once", type: "check" },
		{ key: "allow_bulk_edit", label: "Allow Bulk Edit", type: "check", show: t === "Table" },
		{ key: "permlevel", label: "Perm Level", type: "int" },
		{ key: "ignore_user_permissions", label: "Ignore User Permissions", type: "check" },
		{ key: "allow_on_submit", label: "Allow on Submit", type: "check" },
		{ key: "report_hide", label: "Report Hide", type: "check" },
		{
			key: "remember_last_selected_value",
			label: "Remember Last Selected Value",
			type: "check",
			show: t === "Link",
		},
		{
			key: "ignore_xss_filter",
			label: "Ignore XSS Filter",
			type: "check",
			hint: "Don't encode HTML tags like <script> or just characters like < or >, as they could be intentionally used in this field.",
		},
		{ key: "in_filter", label: "In Filter", type: "check" },
		{ key: "no_copy", label: "No Copy", type: "check" },
		{ key: "print_hide", label: "Print Hide", type: "check" },
		{
			key: "print_hide_if_no_value",
			label: "Print Hide If No Value",
			type: "check",
			show: _NUMBER_TYPES.has(t),
		},
		{ key: "print_width", label: "Print Width", type: "data" },
		{ key: "width", label: "Width", type: "data" },
		{
			key: "columns",
			label: "Columns",
			type: "int",
			hint: "Number of columns for a field in a List View or a Grid (Total Columns should be less than 11).",
		},
		{ key: "description", label: "Description", type: "textarea" },
		{
			key: "mandatory_depends_on",
			label: "Mandatory Depends On (JS)",
			type: "code",
			mono: true,
			placeholder: "eval:doc.status=='Open'",
		},
		{
			key: "read_only_depends_on",
			label: "Read Only Depends On (JS)",
			type: "code",
			mono: true,
			placeholder: "eval:doc.docstatus==1",
		},
		{ key: "hide_days", label: "Hide Days", type: "check", show: t === "Duration" },
		{ key: "hide_seconds", label: "Hide Seconds", type: "check", show: t === "Duration" },
		{ key: "non_negative", label: "Non Negative", type: "check", show: _NON_NEG_TYPES.has(t) },
		{ key: "max_height", label: "Max Height", type: "data" },
		{ key: "is_virtual", label: "Virtual", type: "check" },
		{ key: "documentation_url", label: "Documentation URL", type: "data", show: t !== "HTML" },
		{ key: "sort_options", label: "Sort Options", type: "check", show: t === "Select" },
		{ key: "show_on_timeline", label: "Show on Timeline", type: "check", show: !!df.hidden },
		{ key: "placeholder", label: "Placeholder", type: "data" },
		{
			key: "make_attachment_public",
			label: "Make Attachment Public (by default)",
			type: "check",
			show: t === "Attach" || t === "Attach Image",
		},
	];
}
