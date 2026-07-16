// Copyright (c) 2026, Kartik Sharma and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Agent Configuration", {
	refresh(frm) {
		frm.events.setup_queries(frm);
		frm.events.render_required_variables(frm);
	},

	setup_queries(frm) {
		frm.set_query('model_override', function () {
			let provider = frm.doc.llm_provider_override;
			if (provider === 'openai') {
				return { filters: { 'provider': 'openai' } };
			} else if (provider === 'gemini') {
				return { filters: { 'provider': 'gemini' } };
			}
			return {};
		});
	},

	render_required_variables(frm) {
		const raw = frm.doc.required_variables;
		const wrapper = frm.fields_dict.required_variables_html.$wrapper;

		if (!raw || !raw.trim()) {
			wrapper.html("");
			return;
		}

		let variables;
		try {
			variables = JSON.parse(raw);
		} catch (e) {
			wrapper.html(
				`<p class="text-muted small">${__("Could not parse required variables.")}</p>`
			);
			return;
		}

		if (!Array.isArray(variables) || variables.length === 0) {
			wrapper.html("");
			return;
		}

		// Group variables by source
		const groups = {};
		for (const v of variables) {
			const source = v.source || "system_prompt";
			if (!groups[source]) {
				groups[source] = [];
			}
			groups[source].push(v);
		}

		// Build a section per group
		let sections = "";
		const sourceKeys = Object.keys(groups);

		// Render system_prompt group first if it exists
		if (groups["system_prompt"]) {
			sections += build_section(
				__("System Prompt"),
				"🔵",
				groups["system_prompt"]
			);
		}

		// Render sub-prompt groups
		for (const key of sourceKeys) {
			if (key === "system_prompt") continue;

			// Find the sub-prompt name from the form data
			let label = key;
			for (const sp of frm.doc.sub_prompts || []) {
				if (sp.sub_agent_id === key) {
					label = sp.sub_agent_name || key;
					break;
				}
			}

			sections += build_section(
				__("Sub-Prompt: {0}", [label]),
				"🟡",
				groups[key]
			);
		}

		wrapper.html(`
			<div class="frappe-card p-3 mb-3">
				<div class="d-flex align-items-center gap-2 mb-2">
					<span>📌</span>
					<span class="font-weight-bold small text-uppercase">
						${__("Required Prompt Variables")}
					</span>
				</div>
				<p class="text-muted small mb-3">
					${__("These variables are injected at runtime. Each prompt must include them as")}
					<code>{variable_name}</code>
					${__("placeholders for the agent to work correctly.")}
				</p>
				${sections}
			</div>
		`);
	},
});

function build_section(title, icon, vars) {
	const rows = vars
		.map(
			(v) => `
		<tr>
			<td><code>{${frappe.utils.escape_html(v.name)}}</code></td>
			<td class="text-muted small">${frappe.utils.escape_html(v.description || "")}</td>
		</tr>`
		)
		.join("");

	return `
		<div class="mb-3">
			<div class="d-flex align-items-center gap-1 mb-1">
				<span>${icon}</span>
				<span class="small font-weight-bold">${title}</span>
			</div>
			<table class="table table-sm table-borderless mb-0">
				<thead>
					<tr>
						<th class="small font-weight-bold" width="200">${__("Variable")}</th>
						<th class="small font-weight-bold">${__("Description")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`;
}
