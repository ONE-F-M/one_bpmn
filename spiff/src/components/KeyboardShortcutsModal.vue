<template>
	<!-- Reference display only. frappe-ui's Dialog closes on an outside click,
	     the X button in its header, and Esc. -->
	<Dialog v-model="open" :options="{ title: 'Keyboard Shortcuts', size: '2xl' }">
		<template #body-content>
			<div class="max-h-[70vh] space-y-6 overflow-y-auto pr-1">
				<section v-for="group in groups" :key="group.title">
					<h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
						{{ group.title }}
					</h3>
					<table class="w-full border-collapse text-sm">
						<thead>
							<tr class="border-b border-gray-200 text-left text-xs text-gray-500">
								<th class="w-2/5 py-1.5 pr-3 font-medium">Action</th>
								<th class="w-[30%] py-1.5 pr-3 font-medium">Windows / Linux</th>
								<th class="w-[30%] py-1.5 font-medium">macOS</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="row in group.rows"
								:key="row.action"
								class="border-b border-gray-100 last:border-0"
							>
								<td class="py-2 pr-3 text-gray-800">{{ row.action }}</td>
								<td class="py-2 pr-3">
									<template v-for="(keys, i) in row.win" :key="keys">
										<span v-if="i > 0" class="mx-1 text-xs text-gray-500">or</span>
										<kbd class="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-xs text-gray-700">{{ keys }}</kbd>
									</template>
								</td>
								<td class="py-2">
									<template v-for="(keys, i) in row.mac" :key="keys">
										<span v-if="i > 0" class="mx-1 text-xs text-gray-500">or</span>
										<kbd class="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-xs text-gray-700">{{ keys }}</kbd>
									</template>
								</td>
							</tr>
						</tbody>
					</table>
				</section>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { Dialog } from "frappe-ui";

const open = defineModel({ type: Boolean, default: false });

// Each platform cell is a list of alternative key combinations.
const groups = [
	{
		title: "Element Manipulation",
		rows: [
			{ action: "Copy Selected Elements", win: ["Ctrl+C"], mac: ["Cmd+C"] },
			{ action: "Cut Selected Elements", win: ["Ctrl+X"], mac: ["Cmd+X"] },
			{ action: "Paste Elements", win: ["Ctrl+V"], mac: ["Cmd+V"] },
			{ action: "Duplicate Elements", win: ["Ctrl+D"], mac: ["Cmd+D"] },
			{ action: "Delete Elements", win: ["Delete", "Backspace"], mac: ["Delete", "Backspace"] },
			{ action: "Multi-Select Elements", win: ["Shift+Click", "Drag"], mac: ["Shift+Click", "Drag"] },
		],
	},
	{
		title: "History & File",
		rows: [
			{ action: "Undo Last Action", win: ["Ctrl+Z"], mac: ["Cmd+Z"] },
			{ action: "Redo Last Action", win: ["Ctrl+Y", "Ctrl+Shift+Z"], mac: ["Cmd+Shift+Z"] },
			{ action: "Save Process Map", win: ["Ctrl+S"], mac: ["Cmd+S"] },
			{ action: "Select All", win: ["Ctrl+A"], mac: ["Cmd+A"] },
		],
	},
	{
		title: "Canvas Navigation",
		rows: [
			{ action: "Zoom In", win: ["Ctrl+Plus"], mac: ["Cmd+Plus"] },
			{ action: "Zoom Out", win: ["Ctrl+Minus"], mac: ["Cmd+Minus"] },
			{ action: "Reset Zoom to 100%", win: ["Ctrl+0"], mac: ["Cmd+0"] },
			{ action: "Pan Canvas", win: ["Spacebar+Drag"], mac: ["Spacebar+Drag"] },
		],
	},
];
</script>
