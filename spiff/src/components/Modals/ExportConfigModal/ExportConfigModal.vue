<template>
	<Dialog v-model="showDialog" :options="{ title: 'Export Configuration', size: 'lg' }">
		<template #body-content>
			<div class="space-y-4">
				<!-- Intro -->
				<div class="text-sm text-gray-600">
					This diagram references external configuration records.
					Select which ones to include in a separate <code class="px-1 py-0.5 bg-gray-100 rounded text-xs font-mono">-config.json</code> file alongside the BPMN export.
				</div>

				<!-- Checkboxes -->
				<div class="space-y-2">
					<label
						v-for="opt in configOptions"
						:key="opt.key"
						class="flex items-center gap-3 p-3 rounded-lg border transition-colors cursor-pointer"
						:class="opt.checked ? 'border-blue-200 bg-blue-50/50' : 'border-gray-200 hover:bg-gray-50'"
					>
						<input
							type="checkbox"
							v-model="opt.checked"
							class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
							:disabled="opt.count === 0"
						/>
						<div class="flex-1 min-w-0">
							<div class="text-sm font-medium text-gray-900">{{ opt.label }}</div>
							<div class="text-xs text-gray-500 mt-0.5">{{ opt.description }}</div>
						</div>
						<span
							class="text-xs font-semibold px-2 py-0.5 rounded-full"
							:class="opt.count > 0 ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'"
						>
							{{ opt.count }}
						</span>
					</label>
				</div>

				<!-- Info note -->
				<div class="flex items-start gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
					<Icon icon="lucide:info" class="w-4 h-4 mt-0.5 shrink-0 text-gray-400" />
					<span>The BPMN file (<code class="font-mono">.bpmn</code>) is always exported. Config records are saved as a separate JSON file.</span>
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="exportBpmnOnly">BPMN Only</Button>
				<Button
					variant="solid"
					@click="exportWithConfig"
					:disabled="!anyChecked"
				>Export BPMN + Config</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { Dialog, Button } from "frappe-ui";
import { Icon } from "@iconify/vue";

const props = defineProps({
	counts: {
		type: Object,
		default: () => ({
			server_scripts: 0,
			workflow_states: 0,
			workflow_action_masters: 0,
		}),
	},
});

const showDialog = defineModel({ type: Boolean, default: false });

const emit = defineEmits(["export-bpmn-only", "export-with-config"]);

const configOptions = ref([
	{
		key: "server_scripts",
		label: "Server Scripts",
		description: "Script Task references (Python code)",
		checked: true,
		count: 0,
	},
	{
		key: "workflow_states",
		label: "Workflow States",
		description: "State records used in workflow transitions",
		checked: true,
		count: 0,
	},
	{
		key: "workflow_action_masters",
		label: "Workflow Action Masters",
		description: "Action labels used in User Task buttons",
		checked: true,
		count: 0,
	},
]);

// Sync counts from prop
watch(
	() => props.counts,
	(c) => {
		for (const opt of configOptions.value) {
			opt.count = c[opt.key] || 0;
			// Auto-uncheck if count is 0
			if (opt.count === 0) opt.checked = false;
			else opt.checked = true;
		}
	},
	{ immediate: true, deep: true }
);

const anyChecked = computed(() => configOptions.value.some((o) => o.checked && o.count > 0));

function exportBpmnOnly() {
	showDialog.value = false;
	emit("export-bpmn-only");
}

function exportWithConfig() {
	const selected = {};
	for (const opt of configOptions.value) {
		selected[opt.key] = opt.checked && opt.count > 0;
	}
	showDialog.value = false;
	emit("export-with-config", selected);
}
</script>
