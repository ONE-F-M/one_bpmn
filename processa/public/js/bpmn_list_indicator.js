/**
 * BPMN Workflow State Indicator (List View + Form View)
 *
 * Overrides the standard frappe.get_indicator() so that DocTypes whose
 * `workflow_state` field is set by the BPMN Orchestrator (Processa) show
 * the workflow state label + colour in BOTH list views and form views,
 * instead of the generic "Draft" / "Submitted" / "Cancelled" docstatus
 * indicator.
 *
 * This works because both the list view (list_view.js get_indicator_html)
 * and the form view (toolbar.js set_indicator) call the same global
 * frappe.get_indicator() function.
 *
 * The Workflow State DocType stores a `style` field (Primary, Success,
 * Warning, Danger, Inverse, Info) which is mapped to CSS indicator colours.
 *
 * Loaded globally via app_include_js in hooks.py.
 */

(function () {
	"use strict";

	/* ── Style → CSS colour mapping (same as frappe/model/indicator.js) ── */
	const STYLE_COLOUR_MAP = {
		"Success": "green",
		"Warning": "orange",
		"Danger": "red",
		"Primary": "blue",
		"Inverse": "black",
		"Info": "light-blue",
	};

	/* ── Cache for Workflow State styles fetched from the server ──────── */
	// Map of workflow_state_name → colour string (e.g. "Pending Review" → "orange")
	const _state_colour_cache = {};
	// Whether we have done the initial bulk-load of all Workflow State records
	let _bulk_loaded = false;

	/**
	 * Bulk-load ALL Workflow State records into the cache.
	 *
	 * This fires once (on first list view render) and avoids N+1 server
	 * calls when many different workflow states appear in the list.
	 */
	function _bulk_load_workflow_states() {
		if (_bulk_loaded) return;

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Workflow State",
				fields: ["name", "style"],
				limit_page_length: 0,
			},
			async: false, // Synchronous — must resolve before indicator renders
			callback: function (r) {
				if (r && r.message) {
					r.message.forEach(function (ws) {
						const colour = STYLE_COLOUR_MAP[ws.style] || "gray";
						_state_colour_cache[ws.name] = colour;
					});
				}
				_bulk_loaded = true;
			},
			error: function () {
				// Allow retry on the next indicator render
				_bulk_loaded = false;
			},
		});
	}

	/**
	 * Look up the indicator colour for a given Workflow State value.
	 *
	 * First checks the local `locals["Workflow State"]` (populated by Frappe
	 * when a native Workflow is active), then falls back to our own cache.
	 *
	 * @param {string} state_value - The workflow_state value on the document.
	 * @returns {string} CSS colour class (e.g. "green", "orange", "gray").
	 */
	function _get_state_colour(state_value) {
		if (!state_value) return "gray";

		// 1. Check Frappe's own locals (available when a Frappe Workflow exists)
		if (locals["Workflow State"] && locals["Workflow State"][state_value]) {
			const style = locals["Workflow State"][state_value].style;
			return STYLE_COLOUR_MAP[style] || "gray";
		}

		// 2. Check our cache
		if (state_value in _state_colour_cache) {
			return _state_colour_cache[state_value];
		}

		// 3. Bulk-load hasn't happened yet — trigger it
		_bulk_load_workflow_states();

		// Check again after bulk load
		if (state_value in _state_colour_cache) {
			return _state_colour_cache[state_value];
		}

		return "gray";
	}

	/* ── Monkey-patch frappe.get_indicator ────────────────────────────── */
	const _original_get_indicator = frappe.get_indicator;

	frappe.get_indicator = function (doc, doctype, show_workflow_state) {
		if (!doc) return _original_get_indicator.call(this, doc, doctype, show_workflow_state);

		if (!doctype) doctype = doc.doctype;

		// Only intercept for DocTypes that:
		//   1. Have NO active Frappe Workflow (workflow_fieldname is null)
		//   2. Have a non-empty workflow_state value on the document
		const workflow_fieldname = frappe.workflow.get_state_fieldname(doctype);
		const has_frappe_workflow = !!workflow_fieldname;

		if (!has_frappe_workflow && doc.workflow_state) {
			const meta = frappe.get_meta(doctype);
			const has_ws_field = meta && meta.fields &&
				meta.fields.some(function (df) {
					return df.fieldname === "workflow_state" && df.fieldtype === "Link" && df.options === "Workflow State";
				});
			if (has_ws_field) {
				const state_value = doc.workflow_state;
				const colour = _get_state_colour(state_value);

				return [
					__(state_value, null, doctype),
					colour,
					"workflow_state,=," + state_value,
				];
			}
		}

		// Default: delegate to the original implementation
		return _original_get_indicator.call(this, doc, doctype, show_workflow_state);
	};

	/* ── Ensure workflow_state is fetched in list queries ─────────────
	 *
	 * base_list.js only adds the workflow_state field when a Frappe
	 * Workflow is configured.  For BPMN-only doctypes we patch
	 * set_stats() to also include it in the query fields and sidebar
	 * stats so list views have the data to render indicators.
	 * ─────────────────────────────────────────────────────────────── */
	const BaseListProto = frappe.views.BaseList.prototype;
	const _original_set_stats = BaseListProto.set_stats;

	BaseListProto.set_stats = function () {
		// Call the original first (adds Frappe Workflow field if applicable)
		_original_set_stats.call(this);

		// Already handled by a Frappe Workflow
		if (this.workflow_state_fieldname) return;

		// Check if this doctype has a workflow_state field (BPMN-managed)
		const meta = frappe.get_meta(this.doctype);
		if (!meta || !meta.fields) return;

		const has_ws_field = meta.fields.some(
			function (df) { return df.fieldname === "workflow_state"; }
		);
		if (!has_ws_field) return;

		// Add workflow_state to the fetched fields and sidebar stats
		this._add_field("workflow_state");
		if (Array.isArray(this.stats) && !this.stats.includes("workflow_state")) {
			this.stats.push("workflow_state");
		}
	};

})();
