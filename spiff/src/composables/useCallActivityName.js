import { frappeRequest } from "frappe-ui";

let _pendingTimer = null;
let _abortController = null;
let _lastCalledElement = null;

/** Cancel any pending timer and abort any in-flight fetch. */
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

/** Remove the injected "Process Name" entry from the properties panel. */
export function removeProcessNameField(propertiesContainer) {
	propertiesContainer.value
		?.querySelector('[data-custom="process-name"]')
		?.remove();
}

/**
 * Inject a "Process Name" display field beneath the "Process ID" entry.
 *
 * @param {object}               element             - bpmn-js element (Call Activity)
 * @param {Ref<HTMLElement|null>} propertiesContainer - Vue ref for the panel element
 * @param {object}               [options]
 * @param {number}               [options.delay=150]  - ms to wait for Preact re-render
 */
export function injectProcessNameField(element, propertiesContainer, { delay = 150 } = {}) {
	cancelPendingInjection();
	_lastCalledElement = undefined;

	_pendingTimer = setTimeout(async () => {
		_pendingTimer = null;

		removeProcessNameField(propertiesContainer);
		if (!propertiesContainer.value) return;

		const labels = propertiesContainer.value.querySelectorAll(
			".bio-properties-panel-label"
		);
		const processIdLabel = Array.from(labels).find(
			(el) => el.textContent.trim() === "Process ID"
		);
		const entryEl = processIdLabel?.closest(".bio-properties-panel-entry");
		if (!entryEl) return;

		const calledElement = element.businessObject?.calledElement;

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

		if (calledElement === _lastCalledElement) {
			return;
		}

		_lastCalledElement = calledElement;

		_abortController = new AbortController();
		const { signal } = _abortController;

		try {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_map_api.resolve_process_model_by_id",
				params: { process_id: calledElement },
			});

			if (signal.aborted) return;

			const record = response?.message || response;
			const resolvedName = record?.title || record?.name || "(not found)";

			const nameEl = propertiesContainer.value?.querySelector(
				'[data-custom="process-name"] [data-process-name]'
			);
			if (nameEl) nameEl.textContent = resolvedName;
		} catch (e) {
			if (signal.aborted) return;
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
 */
export function reinjectIfCalledElementChanged(element, propertiesContainer) {
	const calledElement = element.businessObject?.calledElement;
	if (calledElement === _lastCalledElement) return;
	injectProcessNameField(element, propertiesContainer);
}
