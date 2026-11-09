import { reactive, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { errorText } from "@/utils/evalFormat";

const __ = window.__ && typeof window.__ === "function" ? window.__ : (s) => s;

function sleep(ms) {
	return new Promise((r) => setTimeout(r, ms));
}

export function useEvalSuiteRuns(ctx) {
	const { suiteName, runs, cases, selected, loadError, inProgressMessage } = ctx;
	const runningCase = reactive({});
	const runningSelected = ref(false);
	const runningSuite = ref(false);
	const rechecking = ref(false);
	const recheckingCase = reactive({});

	// Show the run straight away so there is no dead time after the click.
	function optimisticRun(runName, totalCases) {
		runs.value.unshift({
			name: runName,
			display_title: "Run — starting…",
			status: "Running",
			passed_cases: 0,
			total_cases: totalCases,
			started_at: "",
		});
	}

	// Polls quietly (no skeleton flicker) until the run leaves "Running".
	async function pollRun(runName) {
		for (let i = 0; i < 40; i++) {
			await sleep(1500);
			await ctx.fetchDetail(true);
			const r = runs.value.find((x) => x.name === runName);
			if (!r || r.status !== "Running") break;
		}
	}

	async function runCases(caseNames, flag, backend = "live") {
		flag.value = true;
		loadError.value = "";
		inProgressMessage.value = "";
		try {
			const runName = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.eval_runner.run_eval_cases",
				method: "POST",
				params: {
					suite_name: suiteName,
					case_names: caseNames ? JSON.stringify(caseNames) : null,
					backend,
				},
			});
			// A name already in the list is the backend handing back the run in progress.
			if (runs.value.some((r) => r.name === runName)) {
				inProgressMessage.value = __("A run of this suite is already in progress");
			} else {
				optimisticRun(runName, caseNames ? caseNames.length : cases.value.length);
			}
			pollRun(runName);
		} catch (e) {
			console.error("Run failed:", e);
			loadError.value = errorText(e, "Failed to start the run.");
		} finally {
			flag.value = false;
		}
	}

	function runWholeSuite() {
		return runCases(null, runningSuite);
	}

	function runSelected() {
		return runCases(selected.value, runningSelected);
	}

	// Re-check is the replay backend: assertions are re-evaluated against each case's last stored answer.
	function recheckSuite() {
		return runCases(null, rechecking, "replay");
	}

	async function recheckCase(c) {
		recheckingCase[c.name] = true;
		try {
			await runCases([c.name], { value: false }, "replay");
		} finally {
			recheckingCase[c.name] = false;
		}
	}

	async function runCase(c) {
		runningCase[c.name] = true;
		try {
			const runName = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.eval_runner.run_eval_cases",
				method: "POST",
				params: { suite_name: suiteName, case_names: JSON.stringify([c.name]) },
			});
			optimisticRun(runName, 1);
			pollRun(runName);
		} catch (e) {
			console.error("Run failed:", e);
			loadError.value = errorText(e, "Failed to start the run.");
		} finally {
			runningCase[c.name] = false;
		}
	}

	// Refresh as each case lands; pollRun is the fallback when realtime is down.
	function onEvalCaseCompleted(data) {
		if (runs.value.some((r) => r.name === data?.run_name)) ctx.fetchDetail(true);
	}

	return {
		runningCase,
		runningSelected,
		runningSuite,
		rechecking,
		recheckingCase,
		runWholeSuite,
		runSelected,
		recheckSuite,
		recheckCase,
		runCase,
		onEvalCaseCompleted,
	};
}
