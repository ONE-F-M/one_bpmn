import { computed, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { serverMessage } from "@/utils/serverMessage.js";
import { DOCU_API } from "@/utils/docuApi";

export function useDocuAutosave({
	dtName,
	contentCount,
	currentIr,
	appliedName,
	loadIr,
	isRestoring,
	getProcessContext,
	emit,
}) {
	// Auto-save: changes persist to the system automatically (no "Apply" button).
	const saveState = ref("idle"); // idle | saving | saved | error
	const canChange = ref(false);
	const saveError = ref("");
	const listingQuestion = ref("");
	const listingAnswer = ref(null);
	const pendingNotice = ref("");
	const pendingRequest = ref("");
	const pendingParts = computed(() => {
		const at = pendingNotice.value.indexOf(pendingRequest.value);
		if (!pendingRequest.value || at < 0) return null;
		return {
			before: pendingNotice.value.slice(0, at),
			after: pendingNotice.value.slice(at + pendingRequest.value.length),
		};
	});
	const pendingUrl = computed(
		() => `/app/doctype-change-request/${encodeURIComponent(pendingRequest.value)}`,
	);
	const saveNotes = ref("");
	const childChanges = ref([]);
	// A design that failed to save, kept in this browser so the canvas can show the site's form and still offer it back.
	const unsavedDesign = ref("");
	let autosaveTimer = null;
	let autosaveInFlight = false;
	let autosaveQueued = false;

	async function loadCanChange() {
		try {
			canChange.value = Boolean(await frappeRequest({ url: `${DOCU_API}can_change_forms` }));
		} catch {
			canChange.value = false;
		}
	}

	// Auto-save: persist the current design to the system, debounced, on every change.
	function scheduleAutosave() {
		if (isRestoring()) return;
		if (autosaveTimer) clearTimeout(autosaveTimer);
		autosaveTimer = setTimeout(runAutosave, 1500);
	}
	async function runAutosave() {
		// Only save a valid design (a name + at least one real field).
		if (!canChange.value || !dtName.value.trim() || !contentCount.value) return;
		if (autosaveInFlight) {
			autosaveQueued = true;
			return;
		}
		autosaveInFlight = true;
		saveState.value = "saving";
		saveError.value = "";
		saveNotes.value = "";
		try {
			const res = await frappeRequest({
				url: `${DOCU_API}apply_doctype`,
				method: "POST",
				// confirm=1: the builder edits are the user's intent - no extra prompt.
				params: {
					ir: JSON.stringify(currentIr()),
					confirm: 1,
					process: getProcessContext()?.process || undefined,
					list_in_process: listingAnswer.value ?? undefined,
				},
			});
			if (res?.status === "needs_listing_decision") {
				listingQuestion.value = res.message;
				saveState.value = "question";
				return;
			}
			listingQuestion.value = "";
			if (res?.status === "pending_approval") {
				pendingNotice.value = res.message;
				pendingRequest.value = res.request || "";
				saveState.value = "pending";
				return;
			}
			if (res?.name) {
				appliedName.value = res.name;
				emit("applied", res.name); // write the DocType name back onto the shape
			}
			saveNotes.value = (res?.notes || []).join(" ");
			storeUnsaved(null);
			saveState.value = "saved";
		} catch (e) {
			saveError.value = serverMessage(e);
			saveState.value = "error";
			storeUnsaved(JSON.stringify(currentIr()));
		} finally {
			autosaveInFlight = false;
			if (autosaveQueued) {
				autosaveQueued = false;
				scheduleAutosave();
			}
		}
	}

	function answerListing(listIt) {
		listingAnswer.value = listIt ? 1 : 0;
		runAutosave();
	}
	function unsavedKey() {
		return `docu-unsaved:${dtName.value.trim()}`;
	}
	const STORAGE_REFUSED = "This browser does not allow Docu to keep an unsaved design.";
	function storeUnsaved(design) {
		try {
			if (design) localStorage.setItem(unsavedKey(), design);
			else localStorage.removeItem(unsavedKey());
		} catch {
			saveNotes.value = STORAGE_REFUSED;
		}
	}
	function readUnsaved() {
		try {
			return localStorage.getItem(unsavedKey());
		} catch {
			saveNotes.value = STORAGE_REFUSED;
			return null;
		}
	}
	function restoreUnsavedDesign() {
		loadIr(JSON.parse(unsavedDesign.value));
		unsavedDesign.value = "";
	}

	function stopTimers() {
		if (autosaveTimer) {
			clearTimeout(autosaveTimer);
			autosaveTimer = null;
		}
	}

	return {
		saveState,
		canChange,
		saveError,
		listingQuestion,
		pendingNotice,
		pendingRequest,
		pendingParts,
		pendingUrl,
		saveNotes,
		childChanges,
		unsavedDesign,
		loadCanChange,
		scheduleAutosave,
		answerListing,
		restoreUnsavedDesign,
		readUnsaved,
		stopTimers,
	};
}
