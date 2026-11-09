import { computed, ref } from "vue";
import { frappeRequest } from "frappe-ui";

export function useEvalDataset(ctx) {
	const { suiteName, suite } = ctx;
	const datasetScope = ref("suite");
	const showDataset = ref(false);
	const readiness = ref(null);
	const datasetNote = ref("");
	const datasetBusy = ref(false);
	const datasetMessage = ref("");
	const datasetError = ref("");
	const importInput = ref(null);
	const importPreview = ref(null);
	const importPayload = ref("");
	const importFileName = ref("");

	// A suite is the unit a run belongs to; the agent view spans every suite it has.
	const datasetSubject = computed(() =>
		datasetScope.value === "agent"
			? { agent: suite.value.agent_configuration }
			: { suite: suiteName },
	);

	// Best-effort: a suite with no agent has no dataset, and that must not blank the page.
	async function loadReadiness() {
		if (!suite.value.agent_configuration) {
			readiness.value = null;
			return;
		}
		try {
			readiness.value = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.golden_dataset.dataset_readiness",
				method: "GET",
				params: datasetSubject.value,
			});
		} catch {
			readiness.value = null;
		}
	}

	function cancelImport() {
		importPreview.value = null;
		importPayload.value = "";
		importFileName.value = "";
		if (importInput.value) importInput.value.value = "";
	}

	function openDataset() {
		datasetMessage.value = "";
		datasetError.value = "";
		datasetNote.value = "";
		cancelImport();
		showDataset.value = true;
		loadReadiness();
	}

	async function takeSnapshot() {
		datasetBusy.value = true;
		datasetMessage.value = "";
		datasetError.value = "";
		try {
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.golden_dataset.snapshot_dataset",
				method: "POST",
				params: { ...datasetSubject.value, notes: datasetNote.value },
			});
			datasetMessage.value = `Recorded ${res.label} — ${res.case_count} case(s).`;
			await loadReadiness();
		} catch (e) {
			datasetError.value = e.messages?.[0] || e.message || "Could not take a version.";
		} finally {
			datasetBusy.value = false;
		}
	}

	function chooseImportFile() {
		datasetError.value = "";
		datasetMessage.value = "";
		importInput.value?.click();
	}

	// An import overwrites cases that share a title, so it is always previewed first.
	async function previewImport(event) {
		const file = event.target.files?.[0];
		if (!file) return;
		datasetBusy.value = true;
		datasetError.value = "";
		datasetMessage.value = "";
		try {
			const text = await file.text();
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.golden_dataset.import_dataset",
				method: "POST",
				params: { payload: text, suite: suiteName, dry_run: 1 },
			});
			importPayload.value = text;
			importFileName.value = file.name;
			importPreview.value = res;
		} catch (e) {
			cancelImport();
			datasetError.value =
				e.messages?.[0] || e.message || "That file could not be read as a dataset.";
		} finally {
			datasetBusy.value = false;
			if (importInput.value) importInput.value.value = "";
		}
	}

	async function applyImport() {
		datasetBusy.value = true;
		datasetError.value = "";
		try {
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.golden_dataset.import_dataset",
				method: "POST",
				params: { payload: importPayload.value, suite: suiteName, dry_run: 0 },
			});
			datasetMessage.value =
				`Imported ${res.created.length} new and overwrote ${res.updated.length} case(s).` +
				(res.left_alone.length ? ` ${res.left_alone.length} left as they were.` : "");
			cancelImport();
			await ctx.fetchDetail(true);
			await loadReadiness();
		} catch (e) {
			datasetError.value = e.messages?.[0] || e.message || "Could not import.";
		} finally {
			datasetBusy.value = false;
		}
	}

	async function downloadDataset() {
		datasetBusy.value = true;
		datasetError.value = "";
		try {
			const payload = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.golden_dataset.export_dataset",
				method: "GET",
				params: datasetSubject.value,
			});
			const blob = new Blob([JSON.stringify(payload, null, 1)], {
				type: "application/json",
			});
			const link = document.createElement("a");
			link.href = URL.createObjectURL(blob);
			link.download = `${payload.subject}-golden-dataset.json`
				.replace(/\s+/g, "-")
				.toLowerCase();
			link.click();
			URL.revokeObjectURL(link.href);
			datasetMessage.value = `Exported ${payload.case_count} case(s).`;
		} catch (e) {
			datasetError.value = e.messages?.[0] || e.message || "Could not export.";
		} finally {
			datasetBusy.value = false;
		}
	}

	return {
		datasetScope,
		showDataset,
		readiness,
		datasetNote,
		datasetBusy,
		datasetMessage,
		datasetError,
		importInput,
		importPreview,
		importFileName,
		loadReadiness,
		openDataset,
		takeSnapshot,
		chooseImportFile,
		cancelImport,
		previewImport,
		applyImport,
		downloadDataset,
	};
}
