import { ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { agentLabel, errorText } from "@/utils/evalFormat";
import { listAssignableAgents } from "@/composables/useAssignableAgents";

export function useEvalReassign(ctx) {
	const { suiteName, suite } = ctx;
	const showReassign = ref(false);
	const reassignAgent = ref("");
	const reassignOptions = ref([]);
	const reassignError = ref("");
	const savingReassign = ref(false);

	async function openReassign() {
		reassignError.value = "";
		reassignAgent.value = suite.value.agent_configuration || "";
		showReassign.value = true;
		try {
			const agents = await listAssignableAgents();
			// Detaching suits a template pack that is copied rather than run.
			reassignOptions.value = [
				{ label: "No agent (detach this suite)", value: "" },
				...agents.map((a) => ({ label: agentLabel(a), value: a.name })),
			];
		} catch (e) {
			reassignOptions.value = [];
			reassignError.value = errorText(e, "Couldn't load the list of agents.");
		}
	}

	async function doReassign() {
		savingReassign.value = true;
		reassignError.value = "";
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.eval_api.reassign_suite",
				method: "POST",
				params: { suite: suiteName, agent_configuration: reassignAgent.value || null },
			});
			showReassign.value = false;
			// Reload: the header shows the agent's display name, which only the server resolves.
			await ctx.fetchDetail();
		} catch (e) {
			reassignError.value = errorText(e, "Couldn't reassign the suite.");
		} finally {
			savingReassign.value = false;
		}
	}

	return {
		showReassign,
		reassignAgent,
		reassignOptions,
		reassignError,
		savingReassign,
		openReassign,
		doReassign,
	};
}
