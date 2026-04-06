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
		@dblclick.stop="!readonly && startEditing(tab)"
		>
			<!-- Status dot: green = Active, orange = Inactive -->
			<span
				:class="[
					'inline-block w-2 h-2 rounded-full shrink-0',
					(tab.is_active || tab.status === 'Active') ? 'bg-green-400' : 'bg-orange-400'
				]"
				:title="(tab.is_active || tab.status === 'Active') ? 'Active' : 'Inactive'"
			></span>

			<!-- Inline rename input (shown on double-click) -->
			<input
				v-if="editingTab === tab.name"
				ref="renameInputRef"
				v-model="editingName"
				type="text"
				class="bg-transparent border-b border-white/60 text-inherit text-base outline-none px-0 py-0 w-40"
				@blur="finishEditing(tab)"
				@keydown.enter.prevent="finishEditing(tab)"
				@keydown.escape.prevent="cancelEditing"
				@click.stop
			/>
			<span v-else class="truncate max-w-40">{{ tab.model_name }}</span>
		</div>

		<!-- Add tab button (hidden in read-only mode) -->
		<button
			v-if="!readonly"
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

const props = defineProps({
	tabs: {
		type: Array,
		default: () => []
	},
	activeTab: {
		type: String,
		default: null
	},
	readonly: {
		type: Boolean,
		default: false
	}
})

const emit = defineEmits(["select-tab", "add-tab", "rename-tab"])

const editingTab = ref(null)
const editingName = ref("")
const renameInputRef = ref(null)

function startEditing(tab) {
	editingTab.value = tab.name
	editingName.value = tab.model_name
	nextTick(() => {
		const input = renameInputRef.value
		// renameInputRef may be an array when inside v-for
		const el = Array.isArray(input) ? input[0] : input
		if (el) {
			el.focus()
			el.select()
		}
	})
}

function finishEditing(tab) {
	const newName = editingName.value.trim()
	const oldName = tab.model_name
	editingTab.value = null

	if (newName && newName !== oldName) {
		emit("rename-tab", {
			tabName: tab.name,
			oldModelName: oldName,
			newModelName: newName,
		})
	}
}

function cancelEditing() {
	editingTab.value = null
	editingName.value = ""
}
</script>
