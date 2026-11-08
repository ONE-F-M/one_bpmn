<script setup>
import { inject, toRef } from "vue";
import ProsAllyPanel from "@/components/ProsAlly/ProsAllyPanel.vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const readonly = toRef(ed.props, "readonly");
const {
	getCanvasXml,
	getLintIssues,
	getOpenSubProcessId,
	isMobile,
	onProsAllyBpmnGenerated,
	processNameForPanel,
	prosAllyMounted,
	prosAllyPanel,
	showProsAllyPanel,
} = ed;
</script>

<template>
	<!-- ProsAlly Panel - flex sibling so canvas shrinks instead of being covered -->
	<transition name="prosally-slide">
		<div
			v-if="prosAllyMounted && !readonly && !isMobile"
			v-show="showProsAllyPanel"
			class="prosally-panel-container order-first w-[var(--agui-chat-pane,420px)] shrink-0 border-r border-gray-200 flex flex-col z-[50]"
		>
			<ProsAllyPanel
				ref="prosAllyPanel"
				:process-name="processNameForPanel"
				:get-canvas-xml="getCanvasXml"
				:get-scope-id="getOpenSubProcessId"
				:get-lint-issues="getLintIssues"
				@close="showProsAllyPanel = false"
				@bpmn-generated="onProsAllyBpmnGenerated"
			/>
		</div>
	</transition>

	<!-- Mobile: ProsAlly as bottom sheet -->
	<transition name="slide-up">
		<div
			v-if="prosAllyMounted && !readonly && isMobile"
			v-show="showProsAllyPanel"
			class="fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 bg-white z-[65] flex flex-col"
			style="height: 70vh"
		>
			<div class="flex justify-center py-2 border-b border-gray-100 shrink-0">
				<div class="w-10 h-1 bg-gray-300 rounded-full"></div>
			</div>
			<ProsAllyPanel
				ref="prosAllyPanel"
				:process-name="processNameForPanel"
				:get-canvas-xml="getCanvasXml"
				:get-scope-id="getOpenSubProcessId"
				:get-lint-issues="getLintIssues"
				@close="showProsAllyPanel = false"
				@bpmn-generated="onProsAllyBpmnGenerated"
			/>
		</div>
	</transition>
</template>

<style src="./BpmnProsAlly.css"></style>
