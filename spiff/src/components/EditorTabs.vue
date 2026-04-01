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
		@dblclick.stop="startEditing(tab)"
		>
			<!-- Display mode -->
			<span v-if="editingTabName !== tab.name" class="truncate max-w-40">{{ tab.model_name }}</span>

			<!-- Edit mode -->
			<input
				v-else
				ref="editInputRefs"
				type="text"
				v-model="editValue"
				class="bg-transparent border-b border-white/60 outline-none text-inherit font-inherit text-base w-40 px-0 py-0"
				@click.stop
				@keydown.enter.prevent="commitEdit(tab)"
				@keydown.escape.prevent="cancelEdit"
				@blur="commitEdit(tab)"
			/>
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
import { ref, nextTick } from "vue"
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

const emit = defineEmits(["select-tab", "add-tab", "rename-tab"])

const editingTabName = ref(null)
const editValue = ref("")
const editInputRefs = ref([])

function startEditing(tab) {
	editingTabName.value = tab.name
	editValue.value = tab.model_name
	nextTick(() => {
		// editInputRefs is an array due to v-for; grab the first (only visible) input
		const input = editInputRefs.value?.[0]
		if (input) {
			input.focus()
			input.select()
		}
	})
}

function commitEdit(tab) {
	const newName = editValue.value.trim()
	const oldName = tab.model_name

	// Reset editing state first
	editingTabName.value = null

	if (!newName || newName === oldName) {
		return // no change
	}

	emit("rename-tab", { tabName: tab.name, oldModelName: oldName, newModelName: newName })
}

function cancelEdit() {
	editingTabName.value = null
}
</script>
