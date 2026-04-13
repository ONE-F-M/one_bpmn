/**
 * BPMN Form Actions Injector
 * ─────────────────────────────────────────────────────────────────────────────
 * Automatically injects BPMN User Task action buttons into any Frappe form
 * that has an active BPMN Process Instance.  The buttons appear in the
 * standard "Actions" dropdown — the same place as Frappe's native workflow
 * action buttons — so users get a seamless, consistent experience.
 *
 * Loaded globally via app_include_js in hooks.py.
 *
 * IMPORTANT: Uses $(document).on("form-refresh") which Frappe emits at the
 * correct point in the form lifecycle (frappe/public/js/frappe/form/form.js).
 * ─────────────────────────────────────────────────────────────────────────────
 */

frappe.provide('one_bpmn');

(function () {
	'use strict';

	/* ── Internal BPMN doctypes — never inject on these ── */
	const BPMN_INTERNAL_DOCTYPES = new Set([
		'BPMN Process Model',
		'BPMN Process Instance',
		'BPMN Active Task',
		'BPMN Activity Log',
		'BPMN Custom Shape',
		'BPMN Shape Library',
		'BPMN Process DocType',
	]);

	/* ── Marker attribute to identify our injected <li> items ── */
	const BPMN_ACTION_MARKER = '__bpmn_action__';

	/**
	 * Load and inject BPMN task actions for the given form.
	 * Called on every form-refresh document event.
	 */
	async function load_bpmn_actions(frm) {
		if (!frm || frm.is_new()) return;
		if (BPMN_INTERNAL_DOCTYPES.has(frm.doctype)) return;

		// Always clear previously injected items first
		_clear_bpmn_actions(frm);

		try {
			const response = await frappe.call({
				method: 'one_bpmn.api.get_active_bpmn_tasks',
				args: {
					doctype: frm.doctype,
					docname: frm.docname,
				},
				freeze: false,
			});

			const tasks = (response && response.message) ? response.message : [];

			if (!tasks || tasks.length === 0) return;

			let injected = 0;

			tasks.forEach(function (task) {
				// Only show actions for the assigned user (or for all if no user assigned)
				const is_for_me = (
					!task.assigned_user ||
					task.assigned_user === frappe.session.user
				);
				if (!is_for_me) return;

				const actions = (task.task_actions || '')
					.split(',')
					.map(a => a.trim())
					.filter(Boolean);

				actions.forEach(function (action) {
					// add_action_item adds to the Actions dropdown — same as native workflow
					const $item = frm.page.add_action_item(
						__(action),
						function () {
							_confirm_and_apply(frm, task, action);
						}
					);

					// Tag the parent <li> so we can remove it on the next refresh
					if ($item && $item.length) {
						$item.closest('li').attr('data-bpmn-action', BPMN_ACTION_MARKER);
					}

					injected++;
				});
			});

			if (injected > 0) {
				// Reveal the Actions dropdown button (hidden by default)
				frm.page.show_actions_menu();

				// ── Hide native Frappe buttons so BPMN is the only path ──────────
				// The server-side guard already blocks direct submit/cancel on the
				// backend; hiding the buttons here keeps the UX consistent.
				_hide_native_frappe_buttons(frm);
			}

		} catch (err) {
			// Non-fatal — log but don't break the form
			console.warn('[one_bpmn] Failed to load BPMN form actions:', err);
		}
	}

	/**
	 * Hide Frappe's native Submit / Cancel / Amend buttons and any native
	 * workflow action buttons when BPMN is controlling this document.
	 * This makes it clear that the only valid path is through the Actions menu.
	 */
	function _hide_native_frappe_buttons(frm) {
		if (!frm || !frm.page) return;

		// Hide Submit / Cancel / Amend primary/secondary action buttons
		frm.page.btn_primary && frm.page.btn_primary.addClass('hide');
		frm.page.btn_secondary && frm.page.btn_secondary.addClass('hide');

		// Hide any native workflow action items from the standard Actions menu
		// (Frappe adds these as <li> items with class "workflow-action-item" or
		//  with data-label matching known workflow transitions)
		frm.page.actions && frm.page.actions
			.find('li:not([data-bpmn-action])')
			.addClass('bpmn-hidden-native')
			.hide();
	}

	/**
	 * Remove all BPMN-injected action items from the page Actions menu.
	 * Only removes items we tagged — other items are untouched.
	 */
	function _clear_bpmn_actions(frm) {
		if (!frm || !frm.page || !frm.page.actions) return;
		frm.page.actions
			.find(`li[data-bpmn-action="${BPMN_ACTION_MARKER}"]`)
			.remove();
	}

	/**
	 * Show a confirmation dialog before calling the BPMN engine.
	 */
	function _confirm_and_apply(frm, task, action) {
		frappe.confirm(
			__(
				'Apply BPMN action <b>{0}</b> on this document?',
				[action]
			),
			function () {
				_apply_bpmn_action(frm, task, action);
			}
		);
	}

	/**
	 * Call the BPMN engine's complete_task API, then reload the form.
	 */
	function _apply_bpmn_action(frm, task, action) {
		frappe.dom.freeze(__('Applying action…'));

		frappe.call({
			method: 'one_bpmn.api.complete_task',
			args: {
				instance_name: task.instance_name,
				task_id:       task.task_id,
				// The engine evaluates: data.get('action') == 'Submit' / 'Reject'
				data: JSON.stringify({ action: action }),
			},
			callback: function (r) {
				frappe.dom.unfreeze();

				if (r && !r.exc) {
					frappe.show_alert({
						message: __('{0} action applied successfully', [action]),
						indicator: 'green',
					}, 4);

					frm.reload_doc();
				}
			},
			error: function () {
				frappe.dom.unfreeze();
			},
		});
	}

	/* ─────────────────────────────────────────────────────────────────────────
	 * Hook into Frappe's document-level "form-refresh" event.
	 *
	 * Frappe emits $(document).trigger("form-refresh", [frm]) inside
	 * Form.trigger_onload() in frappe/public/js/frappe/form/form.js.
	 * This fires after every form load, navigation, save, submit, and cancel.
	 * It's the official, stable way to hook all form refreshes globally.
	 * ───────────────────────────────────────────────────────────────────────── */
	$(document).on('form-refresh', function (e, frm) {
		load_bpmn_actions(frm);
	});

	/* Expose for debugging in the browser console:
	 *   one_bpmn.load_form_actions(cur_frm)
	 */
	one_bpmn.load_form_actions = load_bpmn_actions;

	console.log('[one_bpmn] BPMN form actions injector loaded ✓');

})();
