<template>
	<details class="rounded-lg border border-gray-200 bg-white text-xs">
		<summary class="cursor-pointer select-none px-3 py-2 font-medium text-gray-700">
			{{ __("Names this script can use without importing") }}
		</summary>
		<div
			v-if="error"
			class="px-3 pb-3 text-red-600"
		>
			{{ error }}
		</div>
		<div
			v-else-if="loading"
			class="px-3 pb-3 text-gray-400"
		>
			{{ __("Loading...") }}
		</div>
		<table
			v-else
			class="w-full border-t border-gray-100"
		>
			<thead class="text-left text-gray-500">
				<tr>
					<th class="px-3 py-1.5 font-medium">{{ __("Name") }}</th>
					<th class="px-3 py-1.5 font-medium">{{ __("Meaning") }}</th>
					<th class="px-3 py-1.5 font-medium">{{ __("Script Task") }}</th>
					<th class="px-3 py-1.5 font-medium">{{ __("Agent tool") }}</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="row in names"
					:key="row.name"
					class="border-t border-gray-100 text-gray-700"
				>
					<td class="px-3 py-1.5 font-mono">{{ row.name }}</td>
					<td class="px-3 py-1.5">{{ row.meaning }}</td>
					<td class="px-3 py-1.5">{{ row.script_task ? __("Yes") : __("No") }}</td>
					<td class="px-3 py-1.5">{{ row.tool ? __("Yes") : __("No") }}</td>
				</tr>
			</tbody>
		</table>
	</details>
</template>

<script setup>
import { useScriptNames } from "@/composables/useScriptNames"

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { names, error, loading } = useScriptNames()
</script>

<style scoped>
summary {
	list-style-position: inside;
}
</style>
