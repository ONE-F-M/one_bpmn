<script setup>
import { inject } from "vue";
import DmnEditor from "@/components/Editor/DmnEditor.vue";
import { PROCESS_KEY } from "@/composables/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	canEditActiveDiagram,
	dmnEditorKey,
	dmnEditorRef,
	dmnEditorTitle,
	dmnEditorXml,
	onDmnXmlChanged,
	showDmnEditorDialog,
} = pc;
</script>

<template>
	<!-- DMN Editor Dialog (Business Rule Task) - autosaves on every change -->
	<Dialog v-model="showDmnEditorDialog" :options="{ title: dmnEditorTitle, size: '7xl' }">
		<template #body-content>
			<div class="dmn-dialog-body">
				<DmnEditor
					v-if="showDmnEditorDialog"
					:key="dmnEditorKey"
					ref="dmnEditorRef"
					:initial-xml="dmnEditorXml"
					:readonly="!canEditActiveDiagram"
					@xml-changed="onDmnXmlChanged"
				/>
			</div>
		</template>
	</Dialog>
</template>

<style scoped src="./processPageDialogs.css"></style>

<style scoped>
/* DMN Editor Dialog - near-full-screen experience */
:deep(.dialog-content:has(.dmn-dialog-body)) {
	max-width: min(92vw, 1520px) !important;
	width: min(92vw, 1520px) !important;
}

.dmn-dialog-body {
	height: 70vh;
	min-height: 500px;
	display: flex;
	flex-direction: column;
	padding: 0 !important;
	overflow: hidden;
}
</style>
