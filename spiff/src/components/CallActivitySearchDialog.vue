<template>
	<Dialog :modelValue="modelValue" :options="{ title: 'Select Process', size: '2xl' }" @update:modelValue="onDialogToggle">
		<template #body-content>
			<div class="space-y-4">
				<!-- Current value indicator -->
				<div v-if="currentProcessId" class="flex items-center gap-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-sm">
					<Icon icon="lucide:link" class="w-4 h-4 text-blue-500 shrink-0" />
					<span class="text-blue-700 font-medium">Currently linked:</span>
					<code class="text-blue-800 bg-blue-100 px-1.5 py-0.5 rounded font-mono text-xs">{{ currentProcessId }}</code>
				</div>

				<!-- Search input -->
				<div class="relative">
					<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
					<input
						ref="searchInput"
						v-model="searchQuery"
						type="text"
						placeholder="Search by process name or ID..."
						class="w-full pl-9 pr-4 py-2.5 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
						@input="onSearchInput"
					/>
					<button
						v-if="searchQuery"
						@click="searchQuery = ''"
						class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
					>
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>

				<!-- Loading state -->
				<div v-if="loading" class="flex items-center justify-center py-12">
					<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
				</div>

				<!-- Error state -->
				<div v-else-if="error" class="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
					<Icon icon="lucide:alert-circle" class="w-4 h-4 shrink-0" />
					<span>{{ error }}</span>
					<button @click="fetchModels" class="ml-auto text-red-600 underline hover:no-underline">Retry</button>
				</div>

				<!-- Results list -->
				<div v-else class="border border-gray-200 rounded-lg overflow-hidden">
					<!-- Result count -->
					<div class="px-3 py-2 bg-gray-50 border-b border-gray-200 text-xs text-gray-500 font-medium">
						{{ filteredModels.length }} process{{ filteredModels.length !== 1 ? 'es' : '' }} found
					</div>

					<!-- Empty state -->
					<div v-if="filteredModels.length === 0" class="py-10 text-center text-gray-400">
						<Icon icon="lucide:search-x" class="w-10 h-10 mx-auto mb-2 opacity-40" />
						<p class="text-sm">No processes match "{{ searchQuery }}"</p>
					</div>

					<!-- Model Rows -->
					<ul v-else class="divide-y divide-gray-100 max-h-80 overflow-y-auto">
						<li
							v-for="model in filteredModels"
							:key="model.name"
							:class="[
								'flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors group',
								selectedModel?.name === model.name
									? 'bg-blue-50 border-l-4 border-blue-500'
									: 'hover:bg-gray-50 border-l-4 border-transparent',
							]"
							@click="selectModel(model)"
						>
							<!-- Icon -->
							<div :class="['mt-0.5 p-1.5 rounded-md shrink-0', selectedModel?.name === model.name ? 'bg-blue-100' : 'bg-gray-100 group-hover:bg-gray-200']">
								<Icon icon="lucide:workflow" :class="['w-4 h-4', selectedModel?.name === model.name ? 'text-blue-600' : 'text-gray-500']" />
							</div>

							<!-- Details -->
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2 flex-wrap">
									<span :class="['font-medium text-sm truncate', selectedModel?.name === model.name ? 'text-blue-800' : 'text-gray-900']">
										{{ model.title || model.model_name || model.name }}
									</span>
									<span v-if="model.process_id === currentProcessId" class="shrink-0 px-1.5 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-medium">
										Current
									</span>
								</div>
								<div class="mt-0.5 flex items-center gap-2 flex-wrap">
									<code class="text-xs text-gray-400 font-mono truncate">{{ model.process_id }}</code>
									<span v-if="model.category" class="text-xs text-gray-400">· {{ model.category }}</span>
								</div>
							</div>

							<!-- Selected checkmark -->
							<Icon
								v-if="selectedModel?.name === model.name"
								icon="lucide:check-circle-2"
								class="w-5 h-5 text-blue-600 shrink-0 mt-0.5"
							/>
						</li>
					</ul>
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex items-center justify-end w-full gap-2">
				<Button variant="subtle" @click="cancel">Cancel</Button>
				<Button
					variant="solid"
					:disabled="!selectedModel"
					@click="confirm"
				>
					<template #prefix><Icon icon="lucide:check" class="w-3.5 h-3.5" /></template>
					Select Process
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick } from "vue";
import { frappeRequest, Button } from "frappe-ui";
import { Icon } from "@iconify/vue";

const props = defineProps({
	modelValue: {
		type: Boolean,
		default: false,
	},
	// The raw spiff.callactivity.search event payload
	searchEvent: {
		type: Object,
		default: null,
	},
});

const emit = defineEmits(["update:modelValue", "select", "cancel"]);

const searchInput = ref(null);
const searchQuery = ref("");
const allModels = ref([]);
const selectedModel = ref(null);
const loading = ref(false);
const error = ref(null);

// The process_id currently set on the element
const currentProcessId = computed(() => props.searchEvent?.processId || "");

// Filtered list based on search query
const filteredModels = computed(() => {
	if (!searchQuery.value.trim()) return allModels.value;
	const q = searchQuery.value.trim().toLowerCase();
	return allModels.value.filter((m) => {
		const title = (m.title || m.model_name || m.name || "").toLowerCase();
		const pid = (m.process_id || "").toLowerCase();
		return title.includes(q) || pid.includes(q);
	});
});

// Fetch process models from the backend
async function fetchModels() {
	loading.value = true;
	error.value = null;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.list_process_models",
		});
		allModels.value = response.message || response || [];
	} catch (err) {
		console.error("Failed to fetch process models:", err);
		error.value = "Failed to load process models. Please try again.";
	} finally {
		loading.value = false;
	}
}

function selectModel(model) {
	selectedModel.value = model;
}

function confirm() {
	if (!selectedModel.value) return;
	emit("select", selectedModel.value.process_id);
	close();
}

function cancel() {
	emit("cancel");
	close();
}

function close() {
	emit("update:modelValue", false);
}

function onDialogToggle(val) {
	emit("update:modelValue", val);
	if (!val) {
		// Reset state when dialog closes
		searchQuery.value = "";
		selectedModel.value = null;
	}
}

function onSearchInput() {
	// Clear selection if it no longer matches the filter
	if (selectedModel.value && !filteredModels.value.find((m) => m.name === selectedModel.value.name)) {
		selectedModel.value = null;
	}
}

// Load models and pre-select current when dialog opens
watch(
	() => props.modelValue,
	async (isOpen) => {
		if (isOpen) {
			searchQuery.value = "";
			selectedModel.value = null;
			await fetchModels();
			// Pre-select model matching the current processId
			if (currentProcessId.value) {
				selectedModel.value = allModels.value.find((m) => m.process_id === currentProcessId.value) || null;
			}
			// Focus search input
			await nextTick();
			searchInput.value?.focus();
		}
	}
);
</script>
