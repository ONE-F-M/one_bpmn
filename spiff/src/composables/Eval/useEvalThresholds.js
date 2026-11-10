import { computed, reactive, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { errorText } from "@/utils/evalFormat";

export function useEvalThresholds(ctx) {
	const { suiteName, suite, cases } = ctx;
	const showThresholds = ref(false);
	const savingThresholds = ref(false);
	const thresholdError = ref("");
	const thresholdForm = reactive({
		pass_k: 1,
		min_pass_rate: 0,
		gate_deployment: false,
		ci_role: "",
	});

	// Cases whose every assertion needs a model: a Smoke run skips them and a suite of only these fails.
	const smokeUncheckableCases = computed(() =>
		cases.value.filter((c) => {
			const types = c.assertion_types || [];
			return types.length > 0 && types.every((t) => t === "llm_judge");
		}),
	);

	function openThresholds() {
		thresholdForm.pass_k = suite.value.pass_k || 1;
		thresholdForm.min_pass_rate = suite.value.min_pass_rate || 0;
		thresholdForm.gate_deployment = !!suite.value.gate_deployment;
		thresholdForm.ci_role = suite.value.ci_role || "";
		thresholdError.value = "";
		showThresholds.value = true;
	}

	async function saveThresholds() {
		savingThresholds.value = true;
		thresholdError.value = "";
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.evals.update_suite_thresholds",
				method: "POST",
				params: {
					suite: suiteName,
					pass_k: thresholdForm.pass_k,
					min_pass_rate: thresholdForm.min_pass_rate,
					gate_deployment: thresholdForm.gate_deployment ? 1 : 0,
					ci_role: thresholdForm.ci_role || "",
				},
			});
			showThresholds.value = false;
			await ctx.fetchDetail();
		} catch (e) {
			thresholdError.value = errorText(e, "Could not save.");
		} finally {
			savingThresholds.value = false;
		}
	}

	return {
		showThresholds,
		savingThresholds,
		thresholdError,
		thresholdForm,
		smokeUncheckableCases,
		openThresholds,
		saveThresholds,
	};
}
