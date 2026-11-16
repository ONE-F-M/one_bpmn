<template>
	<div class="h-full flex flex-col bg-gray-50">
		<EvalSuiteHeader />

		<main class="flex-1 p-4 sm:p-6 overflow-auto space-y-6">
			<div v-if="loadError" class="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3">
				{{ loadError }}
			</div>
			<div
				v-if="inProgressMessage"
				class="bg-blue-50 text-blue-700 text-sm rounded-lg px-4 py-3"
			>
				{{ inProgressMessage }}
			</div>

			<EvalSuiteMetrics />
			<EvalConsistencyPanel />
			<EvalCaseList />
			<EvalRunList />
		</main>

		<EvalThresholdsModal />
		<EvalDatasetModal />
		<EvalCaseEditorModal />
		<EvalCompareModal />
		<EvalFromRunModal />
		<EvalReassignModal />
	</div>
</template>

<script setup>
import { onMounted, onUnmounted, provide } from "vue";
import { useRoute, useRouter } from "vue-router";
import EvalCaseEditorModal from "@/components/Modals/EvalCaseEditorModal/EvalCaseEditorModal.vue";
import EvalCaseList from "@/components/Evals/EvalCaseList/EvalCaseList.vue";
import EvalCompareModal from "@/components/Modals/EvalCompareModal/EvalCompareModal.vue";
import EvalConsistencyPanel from "@/components/Evals/EvalConsistencyPanel/EvalConsistencyPanel.vue";
import EvalDatasetModal from "@/components/Modals/EvalDatasetModal/EvalDatasetModal.vue";
import EvalFromRunModal from "@/components/Modals/EvalFromRunModal/EvalFromRunModal.vue";
import EvalReassignModal from "@/components/Modals/EvalReassignModal/EvalReassignModal.vue";
import EvalRunList from "@/components/Evals/EvalRunList/EvalRunList.vue";
import EvalSuiteHeader from "@/components/Evals/EvalSuiteHeader/EvalSuiteHeader.vue";
import EvalSuiteMetrics from "@/components/Evals/EvalSuiteMetrics/EvalSuiteMetrics.vue";
import EvalThresholdsModal from "@/components/Modals/EvalThresholdsModal/EvalThresholdsModal.vue";
import { EVAL_SUITE_KEY, createEvalSuiteContext } from "@/composables/Eval/useEvalSuiteState";

const route = useRoute();
const ctx = createEvalSuiteContext(route, useRouter());
provide(EVAL_SUITE_KEY, ctx);

const { loadError, inProgressMessage, cases, fetchDetail, onEvalCaseCompleted } = ctx;

onUnmounted(() => {
	window.frappe?.realtime?.off("eval_case_completed", onEvalCaseCompleted);
});

onMounted(async () => {
	window.frappe?.realtime?.on("eval_case_completed", onEvalCaseCompleted);
	await fetchDetail();
	ctx.fetchProviders();
	ctx.fetchAiModels();
	ctx.loadSkills();

	// ?case=<name> opens that case in the editor; the Feedback queue links here.
	const wanted = route.query.case;
	if (wanted) {
		const found = (cases.value || []).find((c) => c.name === wanted);
		ctx.openEditCase(found || { name: wanted });
	}
});
</script>
