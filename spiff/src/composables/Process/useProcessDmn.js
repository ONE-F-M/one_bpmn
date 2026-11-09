import { watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useProcessDmn(pc) {
	const { activeDiagramName, showDmnEditorDialog, dmnEditorTitle, dmnEditorXml, dmnEditorKey } =
		pc;

	// Clean up DMN state when the dialog is closed (X button, click-outside, etc.)
	watch(showDmnEditorDialog, (isOpen) => {
		if (!isOpen) {
			pc.activeDmnElement = null;
			pc.activeDmnEventBus = null;
			pc.activeDmnDecisionId = null;
			// Reset XML so the next open doesn't flash stale content
			dmnEditorXml.value = "";
		}
	});

	async function onLaunchDmnEditor(event) {
		const element = event.element;
		if (!element) {
			console.error(
				"[DMN] No element found for DMN editor launch — is a Business Rule Task selected?",
			);
			return;
		}

		// Resolve which decision to load:
		// 1. calledDecisionId from the element's extension attribute (set by dropdown picker)
		// 2. event.value passed from the properties panel
		// 3. Fall back to the element's own ID
		const bo = element.businessObject;
		const calledDecisionId =
			(bo && bo.get("spiffworkflow:calledDecisionId")) || event.value || "";
		const decisionId = calledDecisionId || element.id;
		const elementName = bo?.name || decisionId || "Decision Model";

		pc.activeDmnElement = element;
		pc.activeDmnEventBus = event.eventBus;
		pc.activeDmnDecisionId = decisionId;
		dmnEditorTitle.value = `Edit Decision Model — ${elementName}`;

		console.log(
			`[DMN] Launching editor for element: ${element.id}, decision: ${decisionId}, model: ${activeDiagramName.value}`,
		);

		// Load stored XML from backend
		let storedXml = "";
		if (activeDiagramName.value) {
			try {
				const resp = await frappeRequest({
					url: "/api/method/one_bpmn.api.dmn.get_dmn_xml",
					params: {
						process_model: activeDiagramName.value,
						decision_id: decisionId,
					},
				});
				// frappeRequest unwraps the "message" key automatically.
				// get_dmn_xml returns a plain string; handle both wrapped and raw.
				if (typeof resp === "string") {
					storedXml = resp;
				} else if (resp && typeof resp.message === "string") {
					storedXml = resp.message;
				}
				console.log(
					`[DMN] Loaded stored XML: ${storedXml ? storedXml.length + " chars" : "(empty)"}`,
				);
			} catch (err) {
				console.warn("[DMN] Could not load stored XML:", err);
			}
		}

		dmnEditorXml.value = storedXml;
		dmnEditorKey.value++; // Force a fresh DmnEditor instance
		showDmnEditorDialog.value = true;
	}

	async function onDmnXmlChanged(xml) {
		// Autosave: persist every debounced change to the backend
		if (!xml) {
			console.warn("[DMN] onDmnXmlChanged called with empty XML — skipping save");
			return;
		}
		if (!pc.activeDmnElement) {
			console.warn("[DMN] onDmnXmlChanged: no activeDmnElement — skipping save");
			return;
		}
		if (!activeDiagramName.value) {
			console.warn("[DMN] onDmnXmlChanged: no activeDiagramName — skipping save");
			return;
		}

		const decisionId = pc.activeDmnDecisionId || pc.activeDmnElement.id;
		const elementName = pc.activeDmnElement.businessObject?.name || decisionId;

		console.log(
			`[DMN] Saving DMN XML for decision: ${decisionId}, model: ${activeDiagramName.value}, xml length: ${xml.length}`,
		);

		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.dmn.save_dmn_xml",
				method: "POST",
				params: {
					process_model: activeDiagramName.value,
					decision_id: decisionId,
					decision_name: elementName,
					dmn_xml: xml,
				},
			});
			console.log("[DMN] ✅ Save successful");
		} catch (err) {
			console.error("[DMN] Autosave failed:", err);
		}

		// Write DMN reference back to the BPMN element
		if (pc.activeDmnEventBus && pc.activeDmnElement) {
			pc.activeDmnEventBus.fire("spiff.dmn.edit.update", {
				element: pc.activeDmnElement,
				value: decisionId,
			});
		}
	}

	function closeDmnEditor() {
		showDmnEditorDialog.value = false;
		pc.activeDmnElement = null;
		pc.activeDmnEventBus = null;
	}

	Object.assign(pc, { onLaunchDmnEditor, onDmnXmlChanged, closeDmnEditor });
}
