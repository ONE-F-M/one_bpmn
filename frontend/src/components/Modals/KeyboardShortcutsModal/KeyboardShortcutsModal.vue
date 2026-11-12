<script setup>
import { computed } from "vue";
import { Dialog } from "frappe-ui";

// Reference only: these describe the bindings bpmn-js already provides; nothing is bound here.
const open = defineModel({ type: Boolean, default: false });

const DEL = "Delete / Backspace";
const DRAG = "Shift+Click / Drag";
const PAN = "Spacebar+Drag";

// [action, Windows/Linux, macOS]
const groups = computed(() => [
	{
		title: __("Element Manipulation"),
		rows: [
			[__("Copy Selected Elements"), "Ctrl+C", "Cmd+C"],
			[__("Cut Selected Elements"), "Ctrl+X", "Cmd+X"],
			[__("Paste Elements"), "Ctrl+V", "Cmd+V"],
			[__("Duplicate Elements"), "Ctrl+D", "Cmd+D"],
			[__("Delete Elements"), __(DEL), __(DEL)],
			[__("Multi-Select Elements"), __(DRAG), __(DRAG)],
		],
	},
	{
		title: __("History & File"),
		rows: [
			[__("Undo Last Action"), "Ctrl+Z", "Cmd+Z"],
			[__("Redo Last Action"), `Ctrl+Y ${__("or")} Ctrl+Shift+Z`, "Cmd+Shift+Z"],
			[__("Save Process Map"), "Ctrl+S", "Cmd+S"],
			[__("Select All"), "Ctrl+A", "Cmd+A"],
		],
	},
	{
		title: __("Canvas Navigation"),
		rows: [
			[__("Zoom In"), "Ctrl++", "Cmd++"],
			[__("Zoom Out"), "Ctrl+-", "Cmd+-"],
			[__("Reset Zoom to 100%"), "Ctrl+0", "Cmd+0"],
			[__("Pan Canvas"), __(PAN), __(PAN)],
		],
	},
]);
</script>

<template>
	<Dialog v-model="open" :options="{ title: __('Keyboard Shortcuts'), size: '3xl' }">
		<template #body-content>
			<div class="space-y-5 max-h-[70vh] overflow-y-auto">
				<section v-for="group in groups" :key="group.title">
					<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
						{{ group.title }}
					</h3>
					<table class="w-full text-sm">
						<thead>
							<tr class="text-left text-xs text-gray-500 border-b">
								<th class="py-1.5 pr-3 font-medium w-5/12">{{ __("Action") }}</th>
								<th class="py-1.5 pr-3 font-medium w-4/12">{{ __("Windows / Linux") }}</th>
								<th class="py-1.5 font-medium w-3/12">{{ __("macOS") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in group.rows" :key="row[0]" class="border-b last:border-0">
								<td class="py-1.5 pr-3 text-gray-800">{{ row[0] }}</td>
								<td class="py-1.5 pr-3 font-mono text-xs text-gray-600">{{ row[1] }}</td>
								<td class="py-1.5 font-mono text-xs text-gray-600">{{ row[2] }}</td>
							</tr>
						</tbody>
					</table>
				</section>
			</div>
		</template>
	</Dialog>
</template>
