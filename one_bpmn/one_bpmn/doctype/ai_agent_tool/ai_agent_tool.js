// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
<<<<<<< HEAD
//
// WI-001357 (3-04): guided editor for AI Agent Tool records — designers
// build the input_schema through a parameter dialog instead of hand-writing
// JSON. The serialized shape is exactly what WI-001354 validates and
// WI-001355 compiles: {name: {type, description}} plus a comma-separated
// required_params list.

const PARAM_TYPES = ["string", "integer", "number", "boolean", "array", "object"];

function parse_schema(frm) {
	try {
		const schema = JSON.parse(frm.doc.input_schema || "{}");
		return typeof schema === "object" && schema !== null && !Array.isArray(schema) ? schema : {};
	} catch (e) {
		return {};
	}
}

function required_list(frm) {
	return (frm.doc.required_params || "")
		.split(",")
		.map((p) => p.trim())
		.filter(Boolean);
}

function write_schema(frm, schema, required) {
	frm.set_value("input_schema", JSON.stringify(schema, null, 2));
	frm.set_value("required_params", required.join(", "));
	render_parameter_table(frm);
}

function render_parameter_table(frm) {
	const wrapper = frm.get_field("input_schema").$wrapper;
	let $table = wrapper.parent().find(".ai-tool-param-table");
	if (!$table.length) {
		$table = $('<div class="ai-tool-param-table form-group"></div>').insertBefore(wrapper);
	}

	const schema = parse_schema(frm);
	const required = required_list(frm);
	const names = Object.keys(schema);

	if (!names.length) {
		$table.html(`<div class="text-muted small">${__("No parameters defined yet.")}</div>`);
		return;
	}

	const rows = names
		.map((name) => {
			const def = schema[name] || {};
			const req = required.includes(name)
				? `<span class="indicator-pill red">${__("required")}</span>`
				: "";
			return `<tr>
				<td><code>${frappe.utils.escape_html(name)}</code></td>
				<td>${frappe.utils.escape_html(def.type || "")}</td>
				<td>${frappe.utils.escape_html(def.description || "")}</td>
				<td>${req}</td>
				<td class="text-right">
					<button class="btn btn-xs btn-default ai-tool-remove-param" data-param="${frappe.utils.escape_html(name)}">
						${__("Remove")}
					</button>
				</td>
			</tr>`;
		})
		.join("");

	$table.html(`
		<label class="control-label">${__("Parameters")}</label>
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__("Name")}</th><th>${__("Type")}</th>
				<th>${__("Description")}</th><th></th><th></th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>
	`);

	$table.find(".ai-tool-remove-param").on("click", function () {
		const name = $(this).data("param");
		const next_schema = parse_schema(frm);
		delete next_schema[name];
		write_schema(
			frm,
			next_schema,
			required_list(frm).filter((p) => p !== name)
		);
	});
}

function open_parameter_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Parameter"),
		fields: [
			{
				fieldname: "param_name",
				fieldtype: "Data",
				label: __("Parameter Name"),
				reqd: 1,
				description: __("snake_case, e.g. customer_name"),
			},
			{
				fieldname: "param_type",
				fieldtype: "Select",
				label: __("Type"),
				options: PARAM_TYPES.join("\n"),
				default: "string",
				reqd: 1,
			},
			{
				fieldname: "param_description",
				fieldtype: "Small Text",
				label: __("Description"),
				reqd: 1,
				description: __("Shown to the LLM — say what the value means."),
			},
			{
				fieldname: "param_required",
				fieldtype: "Check",
				label: __("Required"),
			},
		],
		primary_action_label: __("Add"),
		primary_action(values) {
			// Client-side validation blocks submission before the doctype's
			// server-side checks (WI-001354) are even reached.
			const name = (values.param_name || "").trim();
			if (!/^[a-z][a-z0-9_]*$/.test(name)) {
				frappe.msgprint(__("Parameter name must be snake_case (letters, digits, underscores)."));
				return;
			}
			if (!values.param_type) {
				frappe.msgprint(__("Every parameter needs a type."));
				return;
			}
			const schema = parse_schema(frm);
			if (schema[name]) {
				frappe.msgprint(__("Parameter '{0}' already exists.", [name]));
				return;
			}
			schema[name] = {
				type: values.param_type,
				description: (values.param_description || "").trim(),
			};
			const required = required_list(frm);
			if (values.param_required) {
				required.push(name);
			}
			write_schema(frm, schema, required);
			dialog.hide();
		},
	});
	dialog.show();
}
=======
>>>>>>> upstream/staging

frappe.ui.form.on("AI Agent Tool", {
	handler_type(frm) {
		// handler_reference targets a different doctype per handler type;
		// clear a stale reference so the Dynamic Link can't point at the
		// wrong doctype. The server-side controller keeps handler_doctype
		// authoritative on validate.
		frm.set_value(
			"handler_doctype",
			frm.doc.handler_type === "call_activity" ? "BPMN Process Model" : "Server Script"
		);
		frm.set_value("handler_reference", "");
	},

	refresh(frm) {
<<<<<<< HEAD
		// Type-to-search over enabled Server Scripts, matching the pattern
		// built for AI Agent Task context fields (WI-001142).
		frm.set_query("handler_reference", () => {
			if (frm.doc.handler_type === "server_script") {
				return { filters: { disabled: 0, script_type: "API" } };
			}
			return {};
		});

		frm.add_custom_button(__("Add Parameter"), () => open_parameter_dialog(frm));
		render_parameter_table(frm);
	},

	input_schema(frm) {
		render_parameter_table(frm);
=======
		frm.set_query("handler_reference", () => {
			if (frm.doc.handler_type === "server_script") {
				return { filters: { disabled: 0 } };
			}
			return {};
		});
>>>>>>> upstream/staging
	},
});
