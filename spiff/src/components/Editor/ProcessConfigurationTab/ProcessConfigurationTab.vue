<script setup>
import { inject } from "vue";
import ConfigImportResultsDialog from "@/components/Modals/ConfigImportResultsModal.vue";
import ExportConfigDialog from "@/components/Modals/ExportConfigModal.vue";
import { PROCESS_KEY } from "@/composables/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	configImportResults,
	configImporting,
	doExportBpmnOnly,
	doExportWithConfig,
	exportConfigCounts,
	handleImportConfigFile,
	handleImportFile,
	importConfigFileInput,
	importFileInput,
	onConfigImportDone,
	showConfigImportResults,
	showExportConfigDialog,
} = pc;
</script>

<template>
	<!-- Hidden file input for BPMN import -->
	<input
		ref="importFileInput"
		type="file"
		accept=".bpmn"
		class="hidden"
		@change="handleImportFile"
	/>

	<!-- Hidden file input for config JSON import -->
	<input
		ref="importConfigFileInput"
		type="file"
		accept=".json"
		class="hidden"
		@change="handleImportConfigFile"
	/>

	<!-- Export Config Dialog -->
	<ExportConfigDialog
		v-model="showExportConfigDialog"
		:counts="exportConfigCounts"
		@export-bpmn-only="doExportBpmnOnly"
		@export-with-config="doExportWithConfig"
	/>

	<!-- Config Import Results Dialog -->
	<ConfigImportResultsDialog
		v-model="showConfigImportResults"
		:results="configImportResults"
		:importing="configImporting"
		@done="onConfigImportDone"
	/>
</template>
