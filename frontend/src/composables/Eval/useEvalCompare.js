import { ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { agentLabel, errorText } from "@/utils/evalFormat";
import { listAssignableAgents } from "@/composables/useAssignableAgents";

export function useEvalCompare(ctx) {
	const { suiteName, suite, router } = ctx;
	const showCompare = ref(false);
	const challenger = ref("");
	const challengerOptions = ref([]);
	const startingCompare = ref(false);
	const compareError = ref("");

	async function openCompare() {
		compareError.value = "";
		challenger.value = "";
		showCompare.value = true;
		try {
			const agents = await listAssignableAgents();
			// The suite's own agent is side A; offering it would only produce a "same agent" refusal.
			challengerOptions.value = agents
				.filter((a) => a.name !== suite.value.agent_configuration)
				.map((a) => ({ label: agentLabel(a), value: a.name }));
		} catch (e) {
			challengerOptions.value = [];
			compareError.value = errorText(e, "Couldn't load the list of agents.");
		}
	}

	async function startComparison() {
		startingCompare.value = true;
		compareError.value = "";
		try {
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_evals.runner.comparison.run_eval_comparison",
				method: "POST",
				params: { suite_name: suiteName, agent_b: challenger.value },
			});
			showCompare.value = false;
			// Both runs are only queued; the comparison page opens on the pair and says so.
			router.push(
				`/processa/evals/compare/${encodeURIComponent(res.run_a)}/${encodeURIComponent(res.run_b)}`,
			);
		} catch (e) {
			compareError.value = errorText(e, "Couldn't start the comparison.");
		} finally {
			startingCompare.value = false;
		}
	}

	return {
		showCompare,
		challenger,
		challengerOptions,
		startingCompare,
		compareError,
		openCompare,
		startComparison,
	};
}
