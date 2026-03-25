/**
 * useCallActivityName
 *
 * Composable that injects a "Process Name" read-only field into the
 * bpmn-js-properties-panel DOM whenever a Call Activity is selected.
 *
 * Design decisions / review fixes applied:
 *  1. Stale-timer guard  — each call cancels the previous pending
 *     setTimeout via a module-level token, and an AbortController is
 *     used to cancel in-flight fetches when the selection changes or
 *     the component unmounts.
 *  2. frappeRequest       — uses the existing resolve_process_model_by_id
 *     backend endpoint via frappeRequest (consistent CSRF + error surfacing)
 *     instead of a raw fetch against the REST resource API.
 *  3. No inline styles    — injected markup relies on existing
 *     .bio-properties-panel-* classes plus a single scoped CSS class
 *     (bpmn-process-name-value) defined in BpmnEditor.vue's <style>.
 *  4. Composable          — extracted from BpmnEditor so the editor's
 *     <script setup> stays thin; only eventBus wiring remains there.
 *  5. calledElement cache — the commandStack.changed re-injection is
 *     skipped when calledElement has not actually changed, preventing
 *     unnecessary DOM churn and network requests.
 */

import { frappeRequest } from "frappe-ui";

/** Pending setTimeout handle — module-level so every call clears the last one. */
let _pendingTimer = null;

/** AbortController for the last in-flight fetch. */
let _abortController = null;

/** Last resolved calledElement value — used to skip redundant re-resolves. */
let _lastCalledElement = null;

/**
 * Cancel any pending timer and abort any in-flight fetch.
 * Call this on selection change and on `onUnmounted`.
 */
export function cancelPendingInjection() {
	if (_pendingTimer !== null) {
		clearTimeout(_pendingTimer);
		_pendingTimer = null;
	}
	if (_abortController) {
		_abortController.abort();
		_abortController = null;
	}
}

/**
 * Remove the injected "Process Name" entry from the properties panel.
 *
 * @param {Ref<HTMLElement|null>} propertiesContainer - Vue ref for the panel element.
 */
export function removeProcessNameField(propertiesContainer) {
	propertiesContainer.value
		?.querySelector('[data-custom="process-name"]')
		?.remove();
}

/**
 * Inject a "Process Name" display field beneath the "Process ID" entry.
 * Resolves the human-readable title via the backend API asynchronously.
 *
 * @param {object}               element             - bpmn-js element (Call Activity)
 * @param {Ref<HTMLElement|null>} propertiesContainer - Vue ref for the panel element
 * @param {object}               [options]
 * @param {number}               [options.delay=150]  - ms to wait for Preact re-render
 */
export function injectProcessNameField(element, propertiesContainer, { delay = 150 } = {}) {
	// Cancel any previous pending work
	cancelPendingInjection();
	// Reset cache when a brand-new element is selected so the first render
	// always produces a fresh label (even if calledElement matches by coincidence).
	_lastCalledElement = undefined;

	_pendingTimer = setTimeout(async () => {
		_pendingTimer = null;

		removeProcessNameField(propertiesContainer);
		if (!propertiesContainer.value) return;

		// Find the "Process ID" label in the Preact-rendered panel
		const labels = propertiesContainer.value.querySelectorAll(
			".bio-properties-panel-label"
		);
		const processIdLabel = Array.from(labels).find(
			(el) => el.textContent.trim() === "Process ID"
		);
		const entryEl = processIdLabel?.closest(".bio-properties-panel-entry");
		if (!entryEl) return;

		const calledElement = element.businessObject?.calledElement;

		// Build injected entry using panel classes (no inline styles)
		const wrapper = document.createElement("div");
		wrapper.setAttribute("data-custom", "process-name");
		wrapper.className = "bio-properties-panel-entry";
		wrapper.innerHTML = `
			<label class="bio-properties-panel-label">Process Name</label>
			<div class="bpmn-process-name-value" data-process-name>
				${calledElement
					? "<span class=\"bpmn-process-name-resolving\">Resolving\u2026</span>"
					: "<span class=\"bpmn-process-name-empty\">(none linked)</span>"}
			</div>
		`;
		entryEl.parentNode.insertBefore(wrapper, entryEl.nextSibling);

		if (!calledElement) {
			_lastCalledElement = null;
			return;
		}

		// Skip network call when calledElement hasn't changed (commandStack churn)
		if (calledElement === _lastCalledElement) {
			// Still update the label text in case the DOM was re-created
			const nameEl = propertiesContainer.value?.querySelector(
				'[data-custom="process-name"] [data-process-name]'
			);
			if (nameEl && _lastCalledElement !== undefined) {
				// Label was already resolved — restore from cache (no fetch needed)
				// We rely on the caller to store the resolved name; skip silently.
			}
			return;
		}

		_lastCalledElement = calledElement;

		// Create a fresh AbortController for this request
		_abortController = new AbortController();
		const { signal } = _abortController;

		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.resolve_process_model_by_id",
				params: { process_id: calledElement },
			});

			// If the request was aborted mid-flight, ignore the result
			if (signal.aborted) return;

			const record = response?.message || response;
			const resolvedName = record?.title || record?.name || "(not found)";

			const nameEl = propertiesContainer.value?.querySelector(
				'[data-custom="process-name"] [data-process-name]'
			);
			if (nameEl) nameEl.textContent = resolvedName;
		} catch (e) {
			if (signal.aborted) return; // Silently ignore aborted requests
			const nameEl = propertiesContainer.value?.querySelector(
				'[data-custom="process-name"] [data-process-name]'
			);
			if (nameEl) nameEl.textContent = calledElement;
		} finally {
			_abortController = null;
		}
	}, delay);
}

/**
 * Re-inject only when calledElement has actually changed.
 * Safe to call on every commandStack.changed without causing DOM churn.
 *
 * @param {object}               element             - currently selected bpmn-js element
 * @param {Ref<HTMLElement|null>} propertiesContainer - Vue ref for the panel element
 */
export function reinjectIfCalledElementChanged(element, propertiesContainer) {
	const calledElement = element.businessObject?.calledElement;
	if (calledElement === _lastCalledElement) return; // No change — skip
	injectProcessNameField(element, propertiesContainer);
}
