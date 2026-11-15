export const SETTING_FLAG_KEYS = [
	"is_submittable",
	"issingle",
	"editable_grid",
	"quick_entry",
	"track_changes",
	"track_seen",
	"track_views",
	"beta",
	"hide_toolbar",
	"allow_copy",
	"allow_rename",
	"allow_import",
	"allow_events_in_timeline",
	"allow_auto_repeat",
	"show_preview_popup",
	"show_name_in_global_search",
	"show_title_field_in_link",
	"translated_doctype",
	"make_attachments_public",
	"is_tree",
];
export const SETTING_INT_KEYS = ["max_attachments"];
export const SETTING_STR_KEYS = [
	"description",
	"image_field",
	"title_field",
	"search_fields",
	"default_print_format",
	"sort_field",
	"sort_order",
	"document_type",
];
export function defaultSettings() {
	const s = {};
	for (const k of SETTING_FLAG_KEYS) s[k] = false;
	for (const k of SETTING_INT_KEYS) s[k] = 0;
	for (const k of SETTING_STR_KEYS) s[k] = "";
	s.editable_grid = true; // Frappe's default for child tables
	s.sort_order = "DESC";
	return s;
}

// Permission rules
// Every right Frappe records, so a rule read off a live DocType survives being
// written back. The grid shows the six a process owner actually decides;
// the rest ride along untouched.
export const PERMISSION_RIGHTS = [
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"if_owner",
];
export const PERMISSION_COLUMNS = [
	{ key: "select", label: "Select" },
	{ key: "read", label: "Read" },
	{ key: "write", label: "Write" },
	{ key: "create", label: "Create" },
	{ key: "delete", label: "Delete" },
	{ key: "submit", label: "Submit" },
];

export function normalizePermission(p) {
	const out = { role: (p?.role || "").trim(), permlevel: Number(p?.permlevel) || 0 };
	for (const r of PERMISSION_RIGHTS) out[r] = p?.[r] ? 1 : 0;
	return out;
}

export function buildSettingsSections(child) {
	const sections = [
		{
			title: "General",
			fields: [
				{ key: "is_submittable", label: "Is Submittable", type: "check", show: !child },
				{ key: "issingle", label: "Is Single", type: "check", show: !child },
				{ key: "editable_grid", label: "Editable Grid", type: "check", show: child },
				{ key: "quick_entry", label: "Quick Entry", type: "check", show: !child },
				{ key: "track_changes", label: "Track Changes", type: "check", show: !child },
				{ key: "track_seen", label: "Track Seen", type: "check", show: !child },
				{ key: "track_views", label: "Track Views", type: "check", show: !child },
				{ key: "beta", label: "Beta", type: "check", show: !child },
			],
		},
		{
			title: "Form Settings",
			show: !child,
			fields: [
				{
					key: "image_field",
					label: "Image Field",
					type: "data",
					placeholder: "an Attach Image fieldname",
				},
				{ key: "max_attachments", label: "Max Attachments", type: "int" },
				{ key: "hide_toolbar", label: "Hide Sidebar, Menu, and Comments", type: "check" },
				{ key: "allow_copy", label: "Hide Copy", type: "check" },
				{ key: "allow_rename", label: "Allow Rename", type: "check" },
				{
					key: "allow_import",
					label: "Allow Import (via Data Import Tool)",
					type: "check",
				},
				{
					key: "allow_events_in_timeline",
					label: "Allow events in timeline",
					type: "check",
				},
				{ key: "allow_auto_repeat", label: "Allow Auto Repeat", type: "check" },
			],
		},
		{
			title: "View Settings",
			show: !child,
			fields: [
				{
					key: "title_field",
					label: "Title Field",
					type: "data",
					placeholder: "a fieldname",
				},
				{
					key: "search_fields",
					label: "Search Fields",
					type: "data",
					placeholder: "comma-separated fieldnames",
				},
				{
					key: "sort_field",
					label: "Default Sort Field",
					type: "data",
					placeholder: "e.g. modified",
				},
				{
					key: "sort_order",
					label: "Default Sort Order",
					type: "select",
					options: ["ASC", "DESC"],
				},
				{ key: "default_print_format", label: "Default Print Format", type: "data" },
				{
					key: "document_type",
					label: "Show in Module Section",
					type: "select",
					options: ["", "Document", "Setup", "System", "Other"],
				},
				{ key: "show_preview_popup", label: "Show Preview Popup", type: "check" },
				{
					key: "show_name_in_global_search",
					label: 'Make "name" searchable in Global Search',
					type: "check",
				},
				{
					key: "show_title_field_in_link",
					label: "Show Title in Link Fields",
					type: "check",
				},
				{ key: "translated_doctype", label: "Translate Link Fields", type: "check" },
				{
					key: "make_attachments_public",
					label: "Make Attachments Public by Default",
					type: "check",
				},
			],
		},
		{
			title: "Advanced",
			fields: [{ key: "is_tree", label: "Is Tree", type: "check", show: !child }],
		},
	];
	return sections
		.filter((s) => s.show !== false)
		.map((s) => ({ ...s, fields: s.fields.filter((f) => f.show !== false) }))
		.filter((s) => s.fields.length);
}
