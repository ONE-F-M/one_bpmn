import { computed } from "vue";

export function useProcessZoom(pc) {
	const { editorRef, currentZoomLevel } = pc;

	// Zoom level (synced with BpmnEditor)
	const zoomLevel = computed(() => currentZoomLevel.value);

	function handleZoomIn() {
		if (editorRef.value) {
			editorRef.value.zoomIn();
			updateZoomLevel();
		}
	}

	function handleZoomOut() {
		if (editorRef.value) {
			editorRef.value.zoomOut();
			updateZoomLevel();
		}
	}

	function handleResetZoom() {
		if (editorRef.value) {
			editorRef.value.resetZoom();
			updateZoomLevel();
		}
	}

	function handleFitToScreen() {
		if (editorRef.value) {
			editorRef.value.fitToScreen();
			// Wait for async zoom update
			setTimeout(() => updateZoomLevel(), 10);
		}
	}

	function updateZoomLevel() {
		if (editorRef.value && typeof editorRef.value.getZoomLevel === "function") {
			currentZoomLevel.value = editorRef.value.getZoomLevel();
		}
	}

	function onZoomChanged(newZoom) {
		currentZoomLevel.value = newZoom;
	}

	Object.assign(pc, {
		zoomLevel,
		handleZoomIn,
		handleZoomOut,
		handleResetZoom,
		handleFitToScreen,
		updateZoomLevel,
		onZoomChanged,
	});
}
