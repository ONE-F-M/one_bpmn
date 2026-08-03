/**
 * BPMN Form Actions Injector
 * Automatically injects BPMN User Task action buttons into any Frappe form
 * that has an active BPMN Process Instance.
 *
 * KEY STRATEGY for hiding Submit/Cancel/Amend:
 *   We override Toolbar.prototype.can_submit at the CLASS level, not the
 *   instance level. This means ANY toolbar instance checks our flag first,
 *   then delegates to the original logic. This avoids all timing issues.
 *
 * TWO LEVELS OF CONTROL (WI-001813):
 *   1. DOCTYPE level — the doctype is run via Processa (an active BPMN
 *      Process Model triggers on it or targets it). Native controls that
 *      Processa owns are suppressed on EVERY document of that doctype:
 *        · the Submit button + "Submit this document to confirm" banner
 *        · the Save button while the document has no unsaved changes
 *      Cancel/Amend and Frappe Workflow buttons are deliberately NOT
 *      suppressed at this level — only per document (level 2).
 *   2. DOCUMENT level — this specific document has a live process instance.
 *      Adds the BPMN action buttons and suppresses Cancel/Amend + native
 *      Frappe Workflow controls.
 *
 * Loaded globally via app_include_js in hooks.py.
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
		'BPMN Process DocType',
	]);

	/* ── Marker attribute to identify our injected <li> items ── */
	const BPMN_ACTION_MARKER = '__bpmn_action__';

	/* ── Track which doctypes+docnames have an active BPMN process ── */
	const _bpmn_controlled_forms = new Set();

	/* ── Doctypes run via Processa (resolved once per page load) ── */
	const _processa_doctypes = new Set();
	let _processa_doctypes_promise = null;

	/**
	 * Fetch the Processa-controlled doctype list once per page load.
	 * Cached server-side in Redis, so this is a single cheap call.
	 */
	function _load_processa_doctypes() {
		if (_processa_doctypes_promise) return _processa_doctypes_promise;

		_processa_doctypes_promise = frappe
			.call({
				method: 'one_bpmn.api.instance_api.get_processa_controlled_doctypes',
				freeze: false,
			})
			.then(function (r) {
				(r && r.message ? r.message : []).forEach(function (dt) {
					_processa_doctypes.add(dt);
				});
				return _processa_doctypes;
			})
			.catch(function (err) {
				console.warn('[one_bpmn] Failed to load Processa doctypes:', err);
				// Allow a later form refresh to retry rather than caching the failure.
				_processa_doctypes_promise = null;
				return _processa_doctypes;
			});

		return _processa_doctypes_promise;
	}

	/** Is this doctype run via Processa? (doctype-level control) */
	function _is_processa_doctype(doctype) {
		return _processa_doctypes.has(doctype);
	}

	/**
	 * Is this form under Processa control at either level?
	 * Doctype-level covers documents with no live instance (never started,
	 * completed or cancelled); document-level covers instances whose process
	 * model has since been deactivated.
	 */
	function _is_processa_governed(frm) {
		if (!frm || !frm.doctype) return false;
		if (BPMN_INTERNAL_DOCTYPES.has(frm.doctype)) return false;
		return (
			_processa_doctypes.has(frm.doctype) ||
			_bpmn_controlled_forms.has(_form_key_from_frm(frm))
		);
	}

	// Override Toolbar PROTOTYPE methods.
	// By wrapping prototype methods we intercept every can_submit / can_cancel / can_amend call,
	// regardless of when Frappe invokes them — far more reliable than patching individual instances.
	const ToolbarProto = frappe.ui.form.Toolbar.prototype;

	const _orig_can_submit = ToolbarProto.can_submit;
	const _orig_can_cancel = ToolbarProto.can_cancel;
	const _orig_can_amend  = ToolbarProto.can_amend;
	const _orig_can_save   = ToolbarProto.can_save;

	ToolbarProto.can_submit = function () {
		// Processa drives submission through its own action buttons — the
		// native Submit button is never the right control on these doctypes.
		if (_is_processa_governed(this.frm)) {
			return false;
		}
		return _orig_can_submit.call(this);
	};

	ToolbarProto.can_save = function () {
		// A saved, unchanged document has nothing to save — the button is a
		// no-op that competes with the Processa actions for attention.
		// New documents keep Save (it is the only way to create them), and a
		// dirty document keeps Save so edits can always be persisted.
		if (
			this.frm &&
			!this.frm.is_new() &&
			!this.frm.is_dirty() &&
			_is_processa_governed(this.frm)
		) {
			return false;
		}
		return _orig_can_save.call(this);
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

	/* ── Never render the "Submit this document to confirm" banner on a
	     Processa-controlled doctype. Suppressing it at the source beats
	     removing it afterwards: no flash, and no dependence on refresh order. ── */
	const FormProto = frappe.ui.form.Form.prototype;
	const _orig_show_submit_message = FormProto.show_submit_message;

	FormProto.show_submit_message = function () {
		if (_is_processa_governed(this)) return;
		return _orig_show_submit_message.call(this);
	};

	/**
	 * Generate a unique key for tracking BPMN-controlled forms.
	 */
	function _form_key_from_frm(frm) {
		return frm.doctype + ':' + frm.docname;
	}

	/**
	 * Remove an already-rendered "Submit this document to confirm" banner.
	 *
	 * Frappe renders it via frm.dashboard.add_comment() → layout.show_message(),
	 * which appends a `.form-message` block into `.form-message-container` —
	 * NOT into the dashboard wrapper. Needed for the first form of a page load,
	 * which can render before the Processa doctype list arrives.
	 */
	function _hide_submit_banner(frm) {
		if (!frm || !frm.layout || !frm.layout.message) return;

		const needle = __('Submit this document to confirm');
		const $container = frm.layout.message;

		$container.find('.form-message').each(function () {
			if (($(this).text() || '').indexOf(needle) !== -1) {
				$(this).remove();
			}
		});

		// Re-hide the container if that was the only message in it
		if (!$container.children().length) {
			$container.addClass('hidden');
		}
	}

	/**
	 * Re-run Frappe's own primary-action logic — but ONLY when the button on
	 * screen is the native Submit / no-op Save we mean to remove.
	 *
	 * Calling set_primary_action() unconditionally would wipe custom primary
	 * actions set by a doctype's own script ("Update", "Get Items", …) — the
	 * pitfall the no-tasks branch below already warns about.
	 */
	function _resync_native_primary_action(frm) {
		if (!frm || !frm.toolbar || !frm.page || !frm.page.btn_primary) return;

		const label = (frm.page.btn_primary.text() || '').trim();
		const is_native_submit = label === __('Submit');
		const is_noop_save = label === __('Save') && !frm.is_dirty();

		if (is_native_submit || is_noop_save) {
			frm.toolbar.set_primary_action();
		}
	}

	// load_bpmn_actions — fires on every form-refresh
	async function load_bpmn_actions(frm) {
		if (!frm || frm.is_new()) {
			return;
		}
		if (BPMN_INTERNAL_DOCTYPES.has(frm.doctype)) return;



		// Always clear previously injected items first
		_clear_bpmn_actions(frm);

		// ── Level 1: doctype-level control ──
		// Resolved once per page load. The first form of a page load can render
		// before this call returns, so clean up whatever already rendered.
		await _load_processa_doctypes();

		if (_is_processa_doctype(frm.doctype)) {
			_hide_submit_banner(frm);
			_resync_native_primary_action(frm);
		}

		try {
			const response = await frappe.call({
				method: 'one_bpmn.api.instance_api.get_active_bpmn_tasks',
				args: {
					doctype: frm.doctype,
					docname: frm.docname,
				},
				freeze: false,
			});

			const tasks = (response && response.message) ? response.message : [];

			if (!tasks || tasks.length === 0) {
				// No BPMN process — unmark and let native buttons work.
				// Do NOT call frm.toolbar.set_primary_action() here —
				// that resets custom primary actions set by other doctypes
				// (e.g. "Update", "Get Items", "Reconcile") back to "Save".
				_bpmn_controlled_forms.delete(_form_key_from_frm(frm));
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
				// assigned_user may list multiple people, comma-joined
				// (Table Field / multi-assignee mode, e.g. Task.custom_assigned_to)
				// — mirrors the Python split_users() helper. An exact string
				// match against the whole joined value would never match any
				// individual assignee once there's more than one.
				const assigned_users_list = (task.assigned_user || '')
					.split(',')
					.map(function (u) { return u.trim(); })
					.filter(Boolean);

				const is_for_me = (
					assigned_users_list.length === 0 ||
					assigned_users_list.indexOf(frappe.session.user) !== -1 ||
					frm.doc.owner === frappe.session.user
				);

				if (!is_for_me) {
					pending_assignee = task.assigned_user;
					return;
				}

				// Use task_actions_detail (structured) if available, else
				// fall back to parsing the comma-separated task_actions string.
				const action_details = _get_action_details(task);

				if (action_details.length > 0) {
					action_details.forEach(function (detail) {
						const $item = frm.page.add_action_item(
							__(detail.action),
							function () {
								_handle_action(frm, task, detail);
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
							_handle_action(frm, task, null);
						}
					);

					if ($item && $item.length) {
						$item.closest('li').attr('data-bpmn-action', BPMN_ACTION_MARKER);
					}

					injected++;
				}
			});

			if (injected > 0) {
				frm.page.show_actions_menu();
				// Doc is saved → show Actions, hide Save
				if (!frm.is_dirty()) {
					frm.page.btn_primary.addClass('hide');
				}
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

		// 1. Hide the "Submit this document to confirm" banner
		_hide_submit_banner(frm);

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
	 * Extract structured action detail objects from a task.
	 *
	 * Prefers task_actions_detail (array of {action, confirmTransition, requireDigitalSignature}).
	 * Falls back to parsing the comma-separated task_actions string.
	 *
	 * @returns {Array<{action: string, confirmTransition?: string, requireDigitalSignature?: string}>}
	 */
	function _get_action_details(task) {
		// Structured format from API
		if (task.task_actions_detail && Array.isArray(task.task_actions_detail) && task.task_actions_detail.length > 0) {
			return task.task_actions_detail.filter(d => d && d.action);
		}
		// Fallback: parse from task_actions string (JSON or legacy CSV)
		const raw = (task.task_actions || '').trim();
		if (!raw) return [];
		// New format: JSON array — [{"action":"Accept"},{"action":"Reject","confirmTransition":"true"}]
		if (raw.startsWith('[')) {
			try {
				const parsed = JSON.parse(raw);
				if (Array.isArray(parsed)) {
					return parsed.filter(d => d && d.action);
				}
			} catch (_) { /* fall through to CSV */ }
		}
		// Legacy: comma-separated action names
		return raw.split(',').map(a => a.trim()).filter(Boolean).map(a => ({ action: a }));
	}

	/**
	 * Handle a BPMN action click, respecting per-action flags:
	 *   - confirmTransition: show confirmation dialog before applying
	 *   - requireDigitalSignature: show placeholder notification (future: signature capture)
	 *
	 * @param {Object} frm - Frappe form instance
	 * @param {Object} task - task object from the API
	 * @param {Object|null} detail - action detail object (null for generic "Complete")
	 */
	function _handle_action(frm, task, detail) {
		const action = detail ? detail.action : null;
		const needsConfirm = detail ? (detail.confirmTransition === 'true') : true;
		const needsSignature = detail ? (detail.requireDigitalSignature === 'true') : false;

		const doApply = function () {
			_apply_bpmn_action(frm, task, action);
		};

		// Digital signature check (placeholder — actual capture UI is a follow-up)
		const doSignatureCheck = function () {
			if (needsSignature) {
				frappe.confirm(
					__('<b>Digital Signature Required</b><br><br>' +
						'This action requires a digital signature to proceed. ' +
						'By clicking "Proceed", you acknowledge and authorize this action with your identity.'),
					function () {
						doApply();
					}
				);
			} else {
				doApply();
			}
		};

		// Confirmation dialog
		if (needsConfirm) {
			const msg = action
				? __('Apply BPMN action <b>{0}</b> on this document?', [action])
				: __('Complete task <b>{0}</b>?', [task.task_name || 'Task']);
			frappe.confirm(msg, function () {
				doSignatureCheck();
			});
		} else {
			doSignatureCheck();
		}
	}

	/**
	 * Extract the human-readable server message from a failed frappe.call and
	 * display it in a styled msgprint dialog instead of a raw browser alert.
	 */
	function _show_task_error(r, xhr) {
		let message = __('An error occurred while completing the task. Please try again.');

		try {
			// Try to pull the message from _server_messages (set by frappe.throw)
			const raw = (r && r._server_messages) || (xhr && JSON.parse(xhr.responseText || '{}')._server_messages);
			if (raw) {
				const msgs = JSON.parse(raw);
				if (msgs && msgs.length) {
					const parsed = JSON.parse(msgs[0]);
					if (parsed.message) message = parsed.message;
				}
			} else if (xhr) {
				// Fallback: pull message from the exception string
				const data = JSON.parse(xhr.responseText || '{}');
				const exc = data.exception || '';
				const match = exc.match(/PermissionError:\s*(.+)/);
				if (match) message = match[1].trim();
			}
		} catch (e) { /* keep default */ }

		frappe.msgprint({
			title: __('Task Not Completed'),
			message: message,
			indicator: 'red',
		});
	}

	/**
	 * Call the BPMN engine's complete_task API, then reload the form.
	 */
	function _apply_bpmn_action(frm, task, action) {
		frappe.dom.freeze(__('Applying action…'));

		frappe.call({
			method: 'one_bpmn.api.instance_api.complete_task',
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
					_show_task_error(r);
				}
			},
			error: function (xhr) {
				frappe.dom.unfreeze();
				_show_task_error(null, xhr);
			},
		});
	}

	// Hook into Frappe form lifecycle via both the native form event system and jQuery fallback.

	// Primary hook — uses Frappe's own form event system on ALL doctypes
	frappe.ui.form.on('*', {
		refresh: function (frm) {
			load_bpmn_actions(frm);
		},
		onload: function (frm) {
			load_bpmn_actions(frm);
		}
	});

	// Fallback — jQuery document event
	$(document).on('form-refresh', function (e, frm) {
		if (_bpmn_controlled_forms.has(_form_key_from_frm(frm))) {
			_hide_native_frappe_ui(frm);
		}
		load_bpmn_actions(frm);
	});

	// When a BPMN-controlled form becomes dirty: show Save, hide Actions.
	// After save → form refreshes → load_bpmn_actions re-runs → shows Actions, hides Save.
	// Frappe triggers $(frm.wrapper).trigger('dirty') — we catch it via delegation.
	$(document).on('dirty', function () {
		if (!cur_frm) return;
		if (!_bpmn_controlled_forms.has(_form_key_from_frm(cur_frm))) return;
		if (!cur_frm.is_dirty()) return;
		// Show Save button
		if (cur_frm.page && cur_frm.page.btn_primary) {
			cur_frm.page.btn_primary.removeClass('hide');
		}
		// Hide BPMN Actions dropdown
		if (cur_frm.page && cur_frm.page.actions_btn_group) {
			cur_frm.page.actions_btn_group.addClass('hide');
		}
	});

	// Realtime: auto-refresh this form when a BPMN task completes (from Processa or another user).
	// Only reload if the event targets the currently open document.
	if (frappe.realtime) {
		frappe.realtime.on('bpmn_instance_updated', function (data) {
			if (!cur_frm || cur_frm.is_new()) return;
			// Only reload if this event is for the current form's document
			if (data.context_doctype && data.context_docname) {
				if (data.context_doctype !== cur_frm.doctype || data.context_docname !== cur_frm.docname) {
					return;
				}
			}
			cur_frm.reload_doc();
		});
	}

	/* Expose for debugging in the browser console */
	one_bpmn.load_form_actions = load_bpmn_actions;
	one_bpmn.bpmn_controlled_forms = _bpmn_controlled_forms;

})();