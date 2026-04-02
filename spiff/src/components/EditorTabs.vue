<template>
	<div class="h-12 flex items-center px-3 gap-2 overflow-x-auto">
		<!-- Tabs -->
		<div
		v-for="tab in tabs"
		:key="tab.name"
		:class="[
			'flex items-center gap-2 px-4 py-2 rounded text-base cursor-pointer transition-colors shrink-0',
			activeTab === tab.name
				? 'bg-gray-700 text-white shadow-sm'
				: 'bg-gray-500 text-gray-100 hover:bg-gray-600'
		]"
		@click="$emit('select-tab', tab.name)"
		>
			<!-- Status dot: green = Active, orange = Inactive -->
			<span
				:class="[
					'inline-block w-2 h-2 rounded-full shrink-0',
					tab.is_active ? 'bg-green-400' : 'bg-orange-400'
				]"
				:title="tab.is_active ? 'Active' : 'Inactive'"
			></span>
			<span class="truncate max-w-40">{{ tab.model_name }}</span>
		</div>

		<!-- Add tab button -->
		<button
			@click="$emit('add-tab')"
			class="p-2 rounded hover:bg-gray-300 text-gray-600 shrink-0"
			title="Add new diagram"
		>
			<Icon icon="lucide:plus" class="w-5 h-5" />
		</button>
	</div>
</template>

<script setup>
import { Icon } from "@iconify/vue"
defineProps({
	tabs: {
		type: Array,
		default: () => []
	},
	activeTab: {
		type: String,
		default: null
	}
})

defineEmits(["select-tab", "add-tab"])
</script>
