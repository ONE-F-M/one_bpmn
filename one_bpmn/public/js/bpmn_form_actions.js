/**
 * BPMN Form Actions Injector
 * ─────────────────────────────────────────────────────────────────────────────
 * Automatically injects BPMN User Task action buttons into any Frappe form
 * that has an active BPMN Process Instance.
 *
 * KEY STRATEGY for hiding Submit/Cancel/Amend:
 *   We override Toolbar.prototype.can_submit at the CLASS level, not the
 *   instance level. This means ANY toolbar instance checks our flag first,
 *   then delegates to the original logic. This avoids all timing issues.
 *
 * Loaded globally via app_include_js in hooks.py.
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

	/* ── Track which doctypes+docnames have an active BPMN process ── */
	const _bpmn_controlled_forms = new Set();

	/* ─────────────────────────────────────────────────────────────────────────
	 * STEP 1: Override Toolbar PROTOTYPE methods.
	 *
	 * By wrapping the prototype methods, we intercept EVERY call to
	 * can_submit / can_cancel / can_amend — no matter when Frappe calls them.
	 * This is far more reliable than patching individual instances.
	 * ───────────────────────────────────────────────────────────────────────── */

	const ToolbarProto = frappe.ui.form.Toolbar.prototype;

	const _orig_can_submit = ToolbarProto.can_submit;
	const _orig_can_cancel = ToolbarProto.can_cancel;
	const _orig_can_amend  = ToolbarProto.can_amend;

	ToolbarProto.can_submit = function () {
		if (this.frm && _bpmn_controlled_forms.has(_form_key_from_frm(this.frm))) {
			return false;
		}
		return _orig_can_submit.call(this);
	};

	ToolbarProto.can_cancel = function () {
		if (this.frm && _bpmn_controlled_forms.has(_form_key_from_frm(this.frm))) {
			return false;
		}
		return _orig_can_cancel.call(this);
	};

	ToolbarProto.can_amend = function () {
		if (this.frm && _bpmn_controlled_forms.has(_form_key_from_frm(this.frm))) {
			return false;
		}
		return _orig_can_amend.call(this);
	};

	/**
	 * Generate a unique key for tracking BPMN-controlled forms.
	 */
	function _form_key_from_frm(frm) {
		return frm.doctype + ':' + frm.docname;
	}

	/* ─────────────────────────────────────────────────────────────────────────
	 * STEP 2: load_bpmn_actions — fires on every form-refresh
	 * ───────────────────────────────────────────────────────────────────────── */

	async function load_bpmn_actions(frm) {
		if (!frm || frm.is_new()) {
			console.log('[one_bpmn] Skipping — frm is new or null');
			return;
		}
		if (BPMN_INTERNAL_DOCTYPES.has(frm.doctype)) return;

		console.log('[one_bpmn] load_bpmn_actions called for:', frm.doctype, frm.docname);

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
			console.log('[one_bpmn] API returned tasks:', tasks.length, tasks);

			if (!tasks || tasks.length === 0) {
				// No BPMN process — unmark and let native buttons work
				_bpmn_controlled_forms.delete(_form_key_from_frm(frm));
				// Re-evaluate toolbar so native buttons come back
				if (frm.toolbar) {
					frm.toolbar.set_primary_action();
				}
				return;
			}

			let injected = 0;
			let pending_assignee = null;

			// Mark this form as BPMN-controlled
			_bpmn_controlled_forms.add(_form_key_from_frm(frm));

			// Force toolbar to re-evaluate — now can_submit returns false
			if (frm.toolbar) {
				frm.toolbar.set_primary_action();
			}

			// Hide the "Submit this document to confirm" banner
			_hide_native_frappe_ui(frm);

			tasks.forEach(function (task) {
				const is_for_me = (
					!task.assigned_user ||
					task.assigned_user === frappe.session.user ||
					frm.doc.owner === frappe.session.user
				);

				if (!is_for_me) {
					pending_assignee = task.assigned_user;
					return;
				}

				const actions = (task.task_actions || '')
					.split(',')
					.map(a => a.trim())
					.filter(Boolean);

				if (actions.length > 0) {
					actions.forEach(function (action) {
						const $item = frm.page.add_action_item(
							__(action),
							function () {
								_confirm_and_apply(frm, task, action);
							}
						);

						if ($item && $item.length) {
							$item.closest('li').attr('data-bpmn-action', BPMN_ACTION_MARKER);
						}

						injected++;
					});
				} else {
					// No actions configured — show a generic "Complete" button
					const $item = frm.page.add_action_item(
						__(task.task_name || 'Complete Task'),
						function () {
							_confirm_and_apply(frm, task, null);
						}
					);

					if ($item && $item.length) {
						$item.closest('li').attr('data-bpmn-action', BPMN_ACTION_MARKER);
					}

					injected++;
				}
			});

			if (injected > 0) {
				console.log('[one_bpmn] Injected', injected, 'BPMN actions, showing menu');
				frm.page.show_actions_menu();
			} else if (pending_assignee) {
				frm.dashboard.add_comment(
					__('This document is controlled by a BPMN process. Pending action from: <b>{0}</b>',
						[pending_assignee]),
					'blue', true
				);
			}

		} catch (err) {
			console.warn('[one_bpmn] Failed to load BPMN form actions:', err);
		}
	}

	/**
	 * Hide all native Frappe UI elements that conflict with BPMN control:
	 *  - "Submit this document to confirm" blue banner
	 *  - Frappe Workflow action buttons (.workflow-button-area)
	 *  - Workflow state indicator bar (.like-disabled-workflow)
	 */
	function _hide_native_frappe_ui(frm) {
		if (!frm) return;

		// 1. Hide the "Submit this document to confirm" dashboard comment
		if (frm.dashboard && frm.dashboard.wrapper) {
			$(frm.dashboard.wrapper).find('.comment-box .alert, .form-message').each(function () {
				let text = $(this).text() || '';
				if (text.includes('Submit this document to confirm')) {
					$(this).remove();
				}
			});
		}

		// 2. Hide Frappe Workflow action buttons
		if (frm.$wrapper) {
			frm.$wrapper
				.find('.workflow-button-area, .form-workflow, .like-disabled-workflow')
				.hide();
		}

		// 3. Hide workflow action buttons from the page header
		if (frm.page && frm.page.wrapper) {
			$(frm.page.wrapper).find('.btn-workflow').hide();
		}
	}

	/**
	 * Remove all BPMN-injected action items from the page Actions menu.
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
		const msg = action
			? __('Apply BPMN action <b>{0}</b> on this document?', [action])
			: __('Complete task <b>{0}</b>?', [task.task_name || 'Task']);
		frappe.confirm(
			msg,
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
				data: action ? JSON.stringify({ action: action }) : '{}',
			},
			callback: function (r) {
				if (r && !r.exc) {
					// Immediately clear BPMN action buttons
					_clear_bpmn_actions(frm);
					if (frm.page) {
						frm.page.hide_actions_menu();
					}

					frappe.dom.unfreeze();

					frappe.show_alert({
						message: __('{0} action applied successfully', [action]),
						indicator: 'green',
					}, 4);

					// Reload to get fresh data from server
					frm.reload_doc();
				} else {
					frappe.dom.unfreeze();
				}
			},
			error: function () {
				frappe.dom.unfreeze();
			},
		});
	}

	/* ─────────────────────────────────────────────────────────────────────────
	 * Hook into Frappe form lifecycle.
	 *
	 * We use BOTH frappe.ui.form.on('*', 'refresh') which is the most
	 * reliable way to hook into every form, AND the jQuery fallback.
	 * ───────────────────────────────────────────────────────────────────────── */

	// Primary hook — uses Frappe's own form event system on ALL doctypes
	frappe.ui.form.on('*', {
		refresh: function (frm) {
			console.log('[one_bpmn] form refresh fired for:', frm.doctype, frm.docname);
			load_bpmn_actions(frm);
		},
		onload: function (frm) {
			console.log('[one_bpmn] form onload fired for:', frm.doctype, frm.docname);
			load_bpmn_actions(frm);
		}
	});

	// Fallback — jQuery document event
	$(document).on('form-refresh', function (e, frm) {
		if (_bpmn_controlled_forms.has(_form_key_from_frm(frm))) {
			if (frm.toolbar) {
				frm.toolbar.set_primary_action();
			}
			_hide_native_frappe_ui(frm);
		}
		load_bpmn_actions(frm);
	});

	// ── Realtime listener: auto-refresh the Frappe form when a BPMN task
	//    completes (from Processa Instance or another user's action) ──────
	if (frappe.realtime) {
		frappe.realtime.on('bpmn_instance_updated', function (data) {
			console.log('[one_bpmn] Realtime bpmn_instance_updated received:', data);
			if (cur_frm && !cur_frm.is_new()) {
				cur_frm.reload_doc();
			}
		});
	}

	/* Expose for debugging in the browser console */
	one_bpmn.load_form_actions = load_bpmn_actions;
	one_bpmn.bpmn_controlled_forms = _bpmn_controlled_forms;

	console.log('[one_bpmn] BPMN form actions injector loaded (prototype override) ✓');

})();
