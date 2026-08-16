// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Connector", {
	refresh(frm) {
		render_icon_preview(frm);

		frm.add_custom_button(__("Validate Configuration"), () => {
			frm.call("validate_configuration").then((r) => {
				const issues = r.message || [];
				if (!issues.length) {
					frappe.show_alert({ message: __("No issues found."), indicator: "green" });
					return;
				}
				frappe.msgprint({
					title: __("{0} issue(s)", [issues.length]),
					indicator: "orange",
					message: issues.map((i) => frappe.utils.escape_html(i)).join("<br>"),
				});
			});
		});

		if (!frm.is_new()) {
			frm.add_custom_button(__("Operations"), () => {
				frappe.set_route("List", "BPMN Connector Operation", { connector: frm.doc.name });
			});
			frm.add_custom_button(__("Export JSON"), () => {
				frappe.call({
					method: "one_bpmn.one_bpmn.connectors.api.export_connector",
					args: { connector_id: frm.doc.name },
					callback: (r) => {
						if (!r.message) return;
						const text = JSON.stringify(r.message, null, 2);
						frappe.msgprint({
							title: __("Manifest JSON"),
							message: `<pre style="max-height:60vh;overflow:auto">${frappe.utils.escape_html(text)}</pre>`,
							wide: true,
						});
					},
				});
			});
		}
	},

	icon_svg_path: render_icon_preview,
	icon_color: render_icon_preview,
});

function render_icon_preview(frm) {
	const wrapper = frm.get_field("icon_preview")?.$wrapper;
	if (!wrapper) return;

	const path = (frm.doc.icon_svg_path || "").trim();
	const color = (frm.doc.icon_color || "#14b8a6").trim();

	if (!path) {
		wrapper.html(
			`<div class="text-muted small">${__("No icon set — Service Tasks show the default plug.")}</div>`
		);
		return;
	}

	// Build via the DOM so path data can never be interpreted as markup.
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 24 24");
	svg.setAttribute("width", "48");
	svg.setAttribute("height", "48");
	const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
	el.setAttribute("d", path);
	el.setAttribute("fill", /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(color) ? color : "#14b8a6");
	svg.appendChild(el);

	wrapper.empty();
	const box = $(
		'<div style="display:flex;align-items:center;gap:12px;padding:8px 12px;' +
			'border:1px solid var(--border-color);border-radius:8px;width:fit-content"></div>'
	);
	box.append(svg);
	box.append(
		`<span class="text-muted small">${__("Drawn on the Service Task in place of the gear")}</span>`
	);
	wrapper.append(box);
}
