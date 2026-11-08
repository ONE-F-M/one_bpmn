import { computed, nextTick, ref } from "vue";

export function useDocuHistory({ currentIr, loadIr }) {
	// Undo/redo (#12) - snapshot the flat IR; restore rebuilds the tree.
	const history = ref([]);
	const histIndex = ref(-1);
	let isRestoring = false;
	let snapTimer = null;
	const canUndo = computed(() => histIndex.value > 0);
	const canRedo = computed(() => histIndex.value < history.value.length - 1);

	function recordSnapshot() {
		if (isRestoring) return;
		const snap = JSON.stringify(currentIr());
		if (history.value[histIndex.value] === snap) return;
		history.value = history.value.slice(0, histIndex.value + 1);
		history.value.push(snap);
		if (history.value.length > 60) history.value.shift();
		histIndex.value = history.value.length - 1;
	}
	function scheduleSnapshot() {
		if (isRestoring) return;
		if (snapTimer) clearTimeout(snapTimer);
		snapTimer = setTimeout(recordSnapshot, 400);
	}
	function restoreSnapshot(snap) {
		isRestoring = true;
		try {
			loadIr(JSON.parse(snap));
		} catch {
			/* ignore malformed snapshot */
		}
		nextTick(() => {
			isRestoring = false;
		});
	}
	function undo() {
		if (!canUndo.value) return;
		if (snapTimer) {
			clearTimeout(snapTimer);
			recordSnapshot();
		} // flush pending edit first
		histIndex.value -= 1;
		restoreSnapshot(history.value[histIndex.value]);
	}
	function redo() {
		if (!canRedo.value) return;
		histIndex.value += 1;
		restoreSnapshot(history.value[histIndex.value]);
	}
	function onGlobalKeydown(e) {
		if (!(e.ctrlKey || e.metaKey)) return;
		const k = (e.key || "").toLowerCase();
		if (k === "z" && !e.shiftKey) {
			e.preventDefault();
			undo();
		} else if ((k === "z" && e.shiftKey) || k === "y") {
			e.preventDefault();
			redo();
		}
	}

	function stopTimers() {
		if (snapTimer) {
			clearTimeout(snapTimer);
			snapTimer = null;
		}
	}

	return {
		canUndo,
		canRedo,
		isRestoring: () => isRestoring,
		scheduleSnapshot,
		recordSnapshot,
		undo,
		redo,
		onGlobalKeydown,
		stopTimers,
	};
}
