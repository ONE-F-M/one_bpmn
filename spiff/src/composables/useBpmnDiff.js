/**
 * useBpmnDiff — composable that encapsulates the BPMN visual diffing logic.
 *
 * Uses `bpmn-js-differ` for semantic comparison and `bpmn-js` canvas markers
 * + overlays for visual highlighting.
 */
import { diff } from "bpmn-js-differ";

/**
 * Parse XML and compute a semantic diff between two BPMN definitions.
 *
 * @param {import('bpmn-js/lib/NavigatedViewer').default} viewerOld  — viewer with old XML already imported
 * @param {import('bpmn-js/lib/NavigatedViewer').default} viewerNew  — viewer with new XML already imported
 * @returns {Object} The diff result with _added, _removed, _changed, _layoutChanged
 */
export function computeDiff(viewerOld, viewerNew) {
	// After importXML, viewer.get('canvas').getRootElement().businessObject.$parent
	// gives us the definitions object. But the simplest API-level access is
	// viewer.getDefinitions() (available on NavigatedViewer / Modeler).
	const oldDefs = viewerOld.getDefinitions();
	const newDefs = viewerNew.getDefinitions();

	if (!oldDefs || !newDefs) {
		console.warn("[useBpmnDiff] Definitions not available — have both XMLs been imported?");
		return { _added: {}, _removed: {}, _changed: {}, _layoutChanged: {} };
	}

	return diff(oldDefs, newDefs);
}

/**
 * Apply visual diff markers (CSS classes + overlay badges) to two viewers.
 *
 * @param {Object} viewerOld
 * @param {Object} viewerNew
 * @param {Object} result — output of computeDiff()
 */
export function applyDiffMarkers(viewerOld, viewerNew, result) {
	// ── Added (green) — new viewer only ──
	for (const id of Object.keys(result._added || {})) {
		safeAddMarker(viewerNew, id, "diff-added");
		addOverlayBadge(viewerNew, id, "marker-added", "+");
	}

	// ── Removed (red) — old viewer only ──
	for (const id of Object.keys(result._removed || {})) {
		safeAddMarker(viewerOld, id, "diff-removed");
		addOverlayBadge(viewerOld, id, "marker-removed", "−");
	}

	// ── Changed (amber) — both viewers ──
	for (const id of Object.keys(result._changed || {})) {
		safeAddMarker(viewerOld, id, "diff-changed");
		safeAddMarker(viewerNew, id, "diff-changed");
		addOverlayBadge(viewerOld, id, "marker-changed", "✎");
		addOverlayBadge(viewerNew, id, "marker-changed", "✎");
	}

	// ── Layout changed (purple) — both viewers ──
	for (const id of Object.keys(result._layoutChanged || {})) {
		safeAddMarker(viewerOld, id, "diff-layout-changed");
		safeAddMarker(viewerNew, id, "diff-layout-changed");
		addOverlayBadge(viewerOld, id, "marker-layout-changed", "⇨");
		addOverlayBadge(viewerNew, id, "marker-layout-changed", "⇨");
	}
}

/**
 * Remove all diff markers and overlays from a viewer.
 */
export function clearDiffMarkers(viewer) {
	if (!viewer) return;

	try { viewer.get("overlays").remove({ type: "diff" }); } catch (_) {}

	const elementRegistry = viewer.get("elementRegistry");
	const canvas = viewer.get("canvas");
	const classes = ["diff-added", "diff-removed", "diff-changed", "diff-layout-changed", "highlight"];

	elementRegistry.forEach((element) => {
		for (const cls of classes) {
			try { canvas.removeMarker(element.id, cls); } catch (_) {}
		}
	});
}

/**
 * Synchronize pan/zoom between two viewers (bi-directional).
 * Returns a teardown function to stop syncing.
 */
export function syncViewers(viewerA, viewerB) {
	let changing = false;

	function update(target) {
		return function (e) {
			if (changing) return;
			changing = true;
			try {
				target.get("canvas").viewbox(e.viewbox);
			} catch (_) {}
			changing = false;
		};
	}

	const handlerAtoB = update(viewerB);
	const handlerBtoA = update(viewerA);

	viewerA.on("canvas.viewbox.changed", handlerAtoB);
	viewerB.on("canvas.viewbox.changed", handlerBtoA);

	return function teardown() {
		viewerA.off("canvas.viewbox.changed", handlerAtoB);
		viewerB.off("canvas.viewbox.changed", handlerBtoA);
	};
}

/**
 * Build a flat list of changes for the overview table.
 *
 * @returns {Array<{id, name, type, change, changeClass}>}
 */
export function buildChangesList(result) {
	const list = [];

	for (const [id, obj] of Object.entries(result._removed || {})) {
		list.push({
			id,
			name: obj.name || "",
			type: (obj.$type || "").replace("bpmn:", ""),
			change: "Removed",
			changeClass: "removed",
			attrs: null,
		});
	}

	for (const [id, obj] of Object.entries(result._added || {})) {
		list.push({
			id,
			name: obj.name || "",
			type: (obj.$type || "").replace("bpmn:", ""),
			change: "Added",
			changeClass: "added",
			attrs: null,
		});
	}

	for (const [id, obj] of Object.entries(result._changed || {})) {
		list.push({
			id,
			name: obj.model?.name || "",
			type: (obj.model?.$type || "").replace("bpmn:", ""),
			change: "Changed",
			changeClass: "changed",
			attrs: obj.attrs || {},
		});
	}

	for (const [id, obj] of Object.entries(result._layoutChanged || {})) {
		list.push({
			id,
			name: obj.name || "",
			type: (obj.$type || "").replace("bpmn:", ""),
			change: "Layout Changed",
			changeClass: "layout-changed",
			attrs: null,
		});
	}

	return list;
}


// ── Internal helpers ──

function safeAddMarker(viewer, elementId, markerClass) {
	try {
		viewer.get("canvas").addMarker(elementId, markerClass);
	} catch (_) {
		// Element may not exist in this viewer (expected for added/removed)
	}
}

function addOverlayBadge(viewer, elementId, className, symbol) {
	try {
		viewer.get("overlays").add(elementId, "diff", {
			position: { top: -12, right: 12 },
			html: `<span class="diff-overlay-badge ${className}">${symbol}</span>`,
		});
	} catch (_) {
		// Element may not exist in this viewer
	}
}
