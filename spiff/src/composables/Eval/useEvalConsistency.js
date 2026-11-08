import { computed, ref } from "vue";
import { frappeRequest } from "frappe-ui";

export function useEvalConsistency(ctx) {
	const { suiteName } = ctx;
	const consistency = ref({});
	const loadingConsistency = ref(false);
	// A case that always agrees with itself is not news.
	const flakyCases = computed(() =>
		(consistency.value.cases || []).filter((c) => c.consistency_rate < 100 || c.flips),
	);

	async function loadConsistency() {
		loadingConsistency.value = true;
		try {
			consistency.value = await frappeRequest({
				url: "/api/method/one_bpmn.api.eval_api.case_consistency",
				method: "GET",
				params: { suite: suiteName },
			});
		} catch (e) {
			console.error("Failed to load the consistency report:", e);
		} finally {
			loadingConsistency.value = false;
		}
	}

	return { consistency, loadingConsistency, flakyCases, loadConsistency };
}
