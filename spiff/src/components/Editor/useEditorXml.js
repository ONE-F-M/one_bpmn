import { layoutBpmnXml } from "@/utils/bpmnLayout.js";

export function useEditorXml(ed) {
	const {
		emit,
		toolbarEl,
		zoomLevel,
		isMounted,
		isImporting,
		modelerInstance,
		internalProcessName,
	} = ed;

	// Empty BPMN diagram template - generates a unique process ID each time
	function makeEmptyDiagram() {
		const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) =>
			b.toString(16).padStart(2, "0"),
		).join("");
		const processId = `Process_${hex}`;
		return `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="${processId}" isExecutable="false" />
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${processId}" />
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;
	}

	// Expose methods for parent component
	async function getXML() {
		if (!ed.modeler) return "";

		// Flush active properties panel text inputs to commit debounced values
		if (document.activeElement && typeof document.activeElement.blur === "function") {
			document.activeElement.blur();
		}

		// Commit any active direct editing on the canvas
		try {
			const directEditing = ed.modeler.get("directEditing");
			if (directEditing && directEditing.isActive()) {
				directEditing.complete();
			}
		} catch (e) {
			console.warn("Could not complete active direct editing:", e);
		}

		// bpmn-js's bpmnDiOrdering rewrites every root's DI on saveXML.start and
		// crashes with "Cannot read properties of undefined (reading 'set')" when
		// a root has none - canvas.clear() during a re-import (e.g. ProsAlly's
		// Apply to canvas) can leave a transient implicit root without DI, and a
		// debounced auto-save can land inside that window. Drop DI-less roots before serializing; they carry nothing
		// the XML needs.
		try {
			const canvas = ed.modeler.get("canvas");
			for (const root of canvas.getRootElements()) {
				if (!root.di && typeof canvas.removeRootElement === "function") {
					canvas.removeRootElement(root);
				}
			}
		} catch (e) {
			console.warn("Could not prune DI-less roots before save:", e);
		}

		const { xml } = await ed.modeler.saveXML({ format: true });
		return xml;
	}

	async function loadXML(xml) {
		if (!ed.modeler) return;
		isImporting.value = true;
		try {
			await ed.modeler.importXML(xml);

			// Proactively auto-layout connecting lines (edges) using bpmn-js's native layout engine.
			// This translates straight-line connectors or missing edge DI elements into standard
			// orthogonal Manhattan routing paths that avoid node overlapping.
			try {
				const elementRegistry = ed.modeler.get("elementRegistry");
				const modeling = ed.modeler.get("modeling");
				const connections = elementRegistry.filter(
					(el) =>
						el.type === "bpmn:SequenceFlow" ||
						(el.waypoints && el.source && el.target),
				);
				for (const conn of connections) {
					try {
						// Only re-layout connections that look like diagonal straight lines
						// (2 waypoints where the Y coordinates differ significantly).
						// Do NOT mutate conn.waypoints directly - that corrupts bpmn-js
						// internal state and causes "Cannot read properties of undefined
						// (reading 'segmentIndex')" errors.
						if (
							conn.waypoints &&
							conn.waypoints.length === 2 &&
							Math.abs(conn.waypoints[0].y - conn.waypoints[1].y) > 5
						) {
							modeling.layoutConnection(conn);
						}
					} catch (singleLayoutErr) {
						// Swallow per-connection errors so one bad edge doesn't break the rest
						console.warn(
							"Auto-layout skipped for connection",
							conn.id,
							singleLayoutErr,
						);
					}
				}
			} catch (layoutErr) {
				console.warn("Auto-layout connections failed:", layoutErr);
			}

			ed.updateUndoRedoState();
			ed.renderComments();
			// Fit diagram to screen by default after loading, safely catching zero-dimension errors
			setTimeout(() => {
				try {
					const canvas = ed.modeler.get("canvas");
					canvas.zoom("fit-viewport");
					zoomLevel.value = Math.round(canvas.zoom() * 100);
				} catch (e) {
					console.warn(
						"Could not fit viewport automatically - container may be hidden:",
						e,
					);
				}
			}, 100);

			// Extract process name from the loaded XML so ProsAlly and other
			// consumers use the actual BPMN process name, not the model record name.
			// The pipeline compiler puts the name on bpmn:Participant (pool header),
			// not on bpmn:Process, so we check both.
			try {
				const elementRegistry = ed.modeler.get("elementRegistry");
				let extractedName = "";

				// 1. Check bpmn:Participant first (where pipeline.mjs puts ir.name)
				const participants = elementRegistry.filter(
					(el) => el.type === "bpmn:Participant",
				);
				for (const p of participants) {
					const name = p.businessObject?.name;
					if (name && name !== "Process") {
						extractedName = name;
						break;
					}
				}

				// 2. Fallback: check bpmn:Process name attribute
				if (!extractedName) {
					const processEls = elementRegistry.filter((el) => el.type === "bpmn:Process");
					for (const processEl of processEls) {
						const name = processEl.businessObject?.name;
						if (name) {
							extractedName = name;
							break;
						}
					}
				}

				if (extractedName) {
					internalProcessName.value = extractedName;
				}
			} catch (e) {
				console.warn("Could not extract process name:", e);
			}
		} catch (err) {
			console.error("Failed to import XML:", err);
		} finally {
			isImporting.value = false;
		}
	}

	function getOpenSubProcessId() {
		const root = ed.modeler?.get("canvas").getRootElement()?.businessObject;
		return root?.$type === "bpmn:SubProcess" ? root.id : "";
	}

	async function getCanvasXml() {
		if (!ed.modeler) return "";
		try {
			const { xml } = await ed.modeler.saveXML({ format: false });
			return xml || "";
		} catch {
			return "";
		}
	}

	async function onProsAllyBpmnGenerated(xml) {
		if (!xml) return;
		await loadXML(layoutBpmnXml(xml));
		emit("changed");
	}

	/**
	 * Set the `name` attribute on the first <bpmn:process> element.
	 * Uses the ed.modeler's modeling API so the change is reflected
	 * immediately in the properties panel and serialised into XML on save.
	 */

	function setProcessName(name) {
		if (name) internalProcessName.value = name;
		if (!ed.modeler || !name) return;
		try {
			const elementRegistry = ed.modeler.get("elementRegistry");
			const modeling = ed.modeler.get("modeling");
			// Find the root process element(s)
			const processElements = elementRegistry.filter((el) => el.type === "bpmn:Process");
			for (const processEl of processElements) {
				if (!processEl.businessObject.name) {
					modeling.updateProperties(processEl, { name });
				}
			}
		} catch (e) {
			console.warn("Could not set process name:", e);
		}
	}

	ed.onReady(async () => {
		// Fix unresolved loop data references (from upstream app.js)
		ed.modeler.on("import.parse.complete", (event) => {
			const refs = (event.references || []).filter(
				(r) =>
					r.property === "bpmn:loopDataInputRef" ||
					r.property === "bpmn:loopDataOutputRef",
			);
			const desc =
				ed.modeler._moddle.registry.getEffectiveDescriptor("bpmn:ItemAwareElement");
			refs.forEach((ref) => {
				const props = {
					id: ref.id,
					name: ref.id ? typeof ref.name === "undefined" : ref.name,
				};
				const elem = ed.modeler._moddle.create(desc, props);
				elem.$parent = ref.element;
				ref.element.set(ref.property, elem);
			});
		});

		// Expose modeler instance for child components
		modelerInstance.value = ed.modeler;

		// Import empty diagram
		await ed.modeler.importXML(makeEmptyDiagram());

		// Append toolbar natively to top header
		isMounted.value = true;
		const targetToolbar = document.getElementById("bpmn-editor-toolbar");
		if (targetToolbar && toolbarEl.value) {
			targetToolbar.innerHTML = "";
			targetToolbar.appendChild(toolbarEl.value);
		}
	});

	Object.assign(ed, {
		makeEmptyDiagram,
		getXML,
		loadXML,
		getOpenSubProcessId,
		getCanvasXml,
		onProsAllyBpmnGenerated,
		setProcessName,
	});
}
