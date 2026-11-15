import { computed, reactive, ref, watch } from "vue";
import { frappeRequest } from "frappe-ui";

export function useEvalFromRun(ctx) {
	const { suiteName } = ctx;
	const showFromRun = ref(false);
	const loadingSteps = ref(false);
	const savingFromRun = ref(false);
	const runSteps = ref([]);
	const fromRun = reactive({ run_name: "", step_name: "" });
	// AI Agent Runs offered by the picker; distinct from the suite's own eval runs.
	const agentRuns = ref([]);
	const loadingAgentRuns = ref(false);

	const stepOptions = computed(() =>
		[{ label: "(whole run)", value: "" }].concat(
			runSteps.value.map((s) => ({ label: s.label || s.name, value: s.name })),
		),
	);
	// "2 Aug, 15:29 · Notify Assignee · Success": enough to tell two runs apart.
	const agentRunOptions = computed(() =>
		[{ label: "Select a run…", value: "" }].concat(
			agentRuns.value.map((r) => ({
				label: `${r.when} · ${r.source} · ${r.status}`,
				value: r.name,
			})),
		),
	);

	async function loadAgentRuns() {
		loadingAgentRuns.value = true;
		agentRuns.value = [];
		try {
			agentRuns.value =
				(await frappeRequest({
					url: "/api/method/processa.ai_agent_evals.eval_case_factory.list_runs_for_case_picker",
					method: "GET",
					params: { suite: suiteName },
				})) || [];
		} catch (e) {
			console.error("Loading runs failed:", e);
			agentRuns.value = [];
		} finally {
			loadingAgentRuns.value = false;
		}
	}

	async function loadSteps() {
		loadingSteps.value = true;
		try {
			const res = await frappeRequest({
				url: "/api/method/processa.ai_agent_evals.eval_case_factory.get_run_steps_for_case_picker",
				method: "GET",
				params: { run_name: fromRun.run_name },
			});
			runSteps.value = res || [];
		} catch {
			runSteps.value = [];
		} finally {
			loadingSteps.value = false;
		}
	}

	// Picking a run offers its steps straight away.
	function onRunPicked() {
		fromRun.step_name = "";
		runSteps.value = [];
		if (fromRun.run_name) loadSteps();
	}

	async function createFromRun() {
		savingFromRun.value = true;
		try {
			await frappeRequest({
				url: "/api/method/processa.ai_agent_evals.eval_case_factory.create_eval_case_from_run",
				method: "POST",
				params: {
					run_name: fromRun.run_name,
					step_name: fromRun.step_name || null,
					suite: suiteName,
				},
			});
			showFromRun.value = false;
			fromRun.run_name = "";
			fromRun.step_name = "";
			runSteps.value = [];
			ctx.fetchDetail();
		} catch (e) {
			console.error("Create from run failed:", e);
		} finally {
			savingFromRun.value = false;
		}
	}

	watch(showFromRun, (open) => {
		if (open) loadAgentRuns();
	});

	return {
		showFromRun,
		loadingSteps,
		savingFromRun,
		runSteps,
		fromRun,
		agentRuns,
		loadingAgentRuns,
		stepOptions,
		agentRunOptions,
		onRunPicked,
		createFromRun,
	};
}
