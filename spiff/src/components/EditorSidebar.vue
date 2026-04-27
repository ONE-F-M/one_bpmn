<template>
	<div class="w-64 bg-white border-r flex flex-col h-full">
		<!-- Header -->
		<div class="px-4 py-3 border-b flex items-center justify-between">
			<span class="text-sm font-medium text-gray-700">Diagrams</span>
			<button
				@click="$emit('add-diagram')"
				class="p-1 hover:bg-gray-100 rounded text-gray-500 hover:text-gray-700"
				title="Add new diagram"
			>
				<Icon icon="lucide:plus" class="w-4 h-4" />
			</button>
		</div>

		<!-- Diagram List -->
		<div class="flex-1 overflow-y-auto">
			<div
				v-for="(diagram, index) in diagrams"
				:key="diagram.name"
				:class="[
					'px-4 py-2 cursor-pointer flex items-center gap-2 text-sm border-l-2 transition-colors',
					activeDiagram === diagram.name
						? 'bg-blue-50 border-blue-500 text-blue-700'
						: 'border-transparent hover:bg-gray-50 text-gray-700'
				]"
				@click="$emit('select-diagram', diagram.name)"
			>
				<!-- Checkmark for active -->
				<span v-if="activeDiagram === diagram.name" class="text-blue-500">
					<Icon icon="lucide:check" class="w-4 h-4" />
				</span>
				<span v-else class="w-4"></span>

				<!-- Diagram name -->
				<span class="flex-1 truncate">{{ diagram.model_name }}</span>

				<!-- Active indicator -->
				<span
					:class="[
						'w-2 h-2 rounded-full flex-shrink-0',
						diagram.is_active ? 'bg-green-500' : 'bg-gray-300'
					]"
					:title="diagram.is_active ? 'Active' : 'Inactive'"
				></span>
			</div>

			<!-- Empty state -->
			<div v-if="diagrams.length === 0" class="px-4 py-8 text-center text-gray-400 text-sm">
				No diagrams yet.<br>
				Click + to add your first diagram.
			</div>
		</div>
	</div>
</template>

<script setup>
import { Icon } from "@iconify/vue"
defineProps({
	diagrams: {
		type: Array,
		default: () => []
	},
	activeDiagram: {
		type: String,
		default: null
	}
})

defineEmits(["select-diagram", "add-diagram"])

</script>
