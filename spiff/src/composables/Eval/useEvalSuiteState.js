import { computed, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { errorText, sparklinePoints } from "@/utils/evalFormat";
import { useEvalCaseEditor } from "@/composables/Eval/useEvalCaseEditor";
import { useEvalCompare } from "@/composables/Eval/useEvalCompare";
import { useEvalConsistency } from "@/composables/Eval/useEvalConsistency";
import { useEvalDataset } from "@/composables/Eval/useEvalDataset";
import { useEvalFromRun } from "@/composables/Eval/useEvalFromRun";
import { useEvalLookups } from "@/composables/Eval/useEvalLookups";
import { useEvalReassign } from "@/composables/Eval/useEvalReassign";
import { useEvalSuiteRuns } from "@/composables/Eval/useEvalSuiteRuns";
import { useEvalThresholds } from "@/composables/Eval/useEvalThresholds";

export const EVAL_SUITE_KEY = Symbol("evalSuite");

export function createEvalSuiteContext(route, router) {
	const suiteName = route.params.suite;
	const loading = ref(true);
	const loadError = ref("");
	const inProgressMessage = ref("");
	const suite = ref({});
	const cases = ref([]);
	const runs = ref([]);
	const totalRuns = ref(0);
	const runsStart = ref(0);
	const runsPageLength = ref(25);
	const metrics = ref({});
	const selected = ref([]);

	const runsRangeLabel = computed(
		() =>
			`${runsStart.value + 1} to ${runsStart.value + runs.value.length} of ${totalRuns.value}`,
	);
	// Re-check needs a prior result to read, so it is offered only once the suite has run.
	const canRecheck = computed(() => totalRuns.value > 0);
	const allSelected = computed(
		() => cases.value.length > 0 && selected.value.length === cases.value.length,
	);
	const sparkPoints = computed(() => sparklinePoints(metrics.value.sparkline));
	const rateColour = computed(() => {
		const m = metrics.value?.latest;
		if (!m?.executions) return "text-gray-900";
		if (suite.value.min_pass_rate && m.pass_rate < suite.value.min_pass_rate)
			return "text-red-600";
		return m.pass_rate === 100 ? "text-green-700" : "text-amber-600";
	});

	const ctx = {
		route,
		router,
		suiteName,
		loading,
		loadError,
		inProgressMessage,
		suite,
		cases,
		runs,
		totalRuns,
		runsStart,
		runsPageLength,
		metrics,
		selected,
		runsRangeLabel,
		canRecheck,
		allSelected,
		sparkPoints,
		rateColour,
	};

	async function fetchDetail(silent = false) {
		if (!silent) loading.value = true;
		loadError.value = "";
		try {
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.api.eval_api.get_suite_detail",
				method: "GET",
				params: {
					suite: suiteName,
					start: runsStart.value,
					page_length: runsPageLength.value,
				},
			});
			suite.value = res?.suite || {};
			cases.value = res?.cases || [];
			runs.value = res?.runs || [];
			totalRuns.value = res?.total_runs || 0;
			runsStart.value = res?.start || 0;
			metrics.value = res?.metrics || {};
			// An open consistency report is stale as soon as a new run lands.
			if (ctx.consistency.value.cases) ctx.loadConsistency();
			ctx.loadReadiness();
		} catch (e) {
			console.error("Failed to load suite:", e);
			if (!silent) loadError.value = errorText(e, "Failed to load this suite.");
		} finally {
			if (!silent) loading.value = false;
		}
	}

	function loadRunsPage(from) {
		runsStart.value = Math.max(from, 0);
		fetchDetail(true);
	}

	function toggleAll(e) {
		selected.value = e.target.checked ? cases.value.map((c) => c.name) : [];
	}

	Object.assign(ctx, { fetchDetail, loadRunsPage, toggleAll });
	Object.assign(
		ctx,
		useEvalConsistency(ctx),
		useEvalLookups(),
		useEvalDataset(ctx),
		useEvalSuiteRuns(ctx),
		useEvalCaseEditor(ctx),
		useEvalThresholds(ctx),
		useEvalFromRun(ctx),
		useEvalCompare(ctx),
		useEvalReassign(ctx),
	);
	return ctx;
}
