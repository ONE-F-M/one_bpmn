<script setup>
import { inject } from "vue";
import DmnEditor from "@/components/Editor/DmnEditor/DmnEditor.vue";
import { PROCESS_KEY } from "@/composables/Process/useProcessState";

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

<style scoped src="./ProcessDmnTab.css"></style>
