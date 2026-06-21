<template>
	<div class="h-full flex flex-col min-w-0 overflow-hidden bg-gray-50">
		<!-- Process Tab Bar -->
		<div class="bg-white border-b flex items-center min-h-[40px] sm:min-h-[42px] px-1 gap-0.5 shrink-0 shadow-sm">

			<!-- Mobile: Active tab dropdown (visible < sm) -->
			<div class="sm:hidden flex items-center flex-1 min-w-0 px-1">
				<button
					v-if="openTabs.length > 0"
					@click="showMobileTabMenu = !showMobileTabMenu"
					class="flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium text-gray-800 bg-gray-100 active:bg-gray-200 transition-colors flex-1 min-w-0"
				>
					<span class="truncate">{{ activeTabLabel }}</span>
					<Icon icon="lucide:chevron-down" class="w-4 h-4 text-gray-500 shrink-0" />
				</button>
				<span v-else class="text-sm text-gray-400 px-2">No processes open</span>
			</div>

			<!-- Mobile Tab Dropdown -->
			<div
				v-if="showMobileTabMenu"
				class="sm:hidden fixed inset-0 z-[200]"
				@click="showMobileTabMenu = false"
			>
				<div class="absolute inset-0 bg-black/20" />
				<div
					class="absolute top-[40px] left-2 right-2 bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden max-h-[60vh]"
					@click.stop
				>
					<div class="p-2 border-b border-gray-100">
						<span class="text-xs font-semibold text-gray-400 uppercase tracking-wider px-2">Open Processes</span>
					</div>
					<div class="overflow-y-auto max-h-[50vh]">
						<div
							v-for="tab in openTabs"
							:key="tab.name"
							role="button"
							tabindex="0"
							@click="switchTab(tab.name); showMobileTabMenu = false"
							@keydown.enter.prevent="switchTab(tab.name); showMobileTabMenu = false"
							@keydown.space.prevent="switchTab(tab.name); showMobileTabMenu = false"
							:class="[
								'w-full flex items-center justify-between px-4 py-3 text-left transition-colors',
								activeTab === tab.name
									? 'bg-gray-800 text-white'
									: 'text-gray-700 active:bg-gray-50'
							]"
						>
							<span class="text-sm font-medium truncate">{{ tab.process_name || tab.name }}</span>
							<button
								@click.stop="closeTab(tab.name); if (openTabs.length === 0) showMobileTabMenu = false"
								:class="[
									'p-1.5 rounded-full transition-colors shrink-0 ml-2',
									activeTab === tab.name
										? 'text-white/60 active:bg-white/20'
										: 'text-gray-400 active:bg-gray-200'
								]"
								aria-label="Close process tab"
							>
								<Icon icon="lucide:x" class="w-4 h-4" />
							</button>
						</div>
					</div>
				</div>
			</div>

			<!-- Desktop: Horizontal scrollable tabs (hidden < sm) -->
			<div class="hidden sm:flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto no-scrollbar py-1" style="-webkit-overflow-scrolling: touch;">
				<div
					v-for="tab in openTabs"
					:key="tab.name"
					:class="[
						'flex items-center gap-2 pl-3.5 pr-1 py-1.5 rounded-md text-sm cursor-pointer transition-all duration-150 shrink-0 group',
						activeTab === tab.name
							? 'bg-gray-800 text-white shadow-md'
							: 'text-gray-600 hover:bg-gray-100'
					]"
					@click="switchTab(tab.name)"
				>
					<span class="truncate max-w-[160px] font-medium">{{ tab.process_name || tab.name }}</span>
					<button
						@click.stop="closeTab(tab.name)"
						:class="[
							'p-0.5 rounded transition-colors shrink-0',
							activeTab === tab.name
								? 'hover:bg-white/20 text-white/70 hover:text-white'
								: 'hover:bg-gray-200 text-gray-400 hover:text-gray-600'
						]"
						title="Close"
					>
						<Icon icon="lucide:x" class="w-3.5 h-3.5" />
					</button>
				</div>
			</div>

			<!-- Add Process Button -->
			<button
				@click="showAddDialog = true"
				class="p-2 rounded-md hover:bg-gray-100 active:bg-gray-200 text-gray-500 hover:text-gray-700 transition-colors shrink-0 ml-1"
				title="Open a process"
			>
				<Icon icon="lucide:plus" class="w-5 h-5" />
			</button>
		</div>

		<!-- Canvas Area -->
		<div class="flex-1 relative overflow-hidden">
			<!-- Render Editor for each open tab; mount only the active tab to avoid duplicate global listeners/heartbeats -->
			<template v-for="tab in openTabs" :key="tab.name">
				<div
					v-if="activeTab === tab.name"
					class="absolute inset-0"
				>
					<Editor
						:process="tab.name"
						:compact="true"
					/>
				</div>
			</template>

			<!-- Empty State -->
			<div
				v-if="openTabs.length === 0"
				class="flex items-center justify-center h-full px-6"
			>
				<div class="text-center max-w-md">
					<div class="mx-auto w-16 h-16 sm:w-20 sm:h-20 rounded-2xl bg-gray-100 flex items-center justify-center mb-4 sm:mb-6">
						<Icon icon="lucide:layers" class="w-8 h-8 sm:w-10 sm:h-10 text-gray-400" />
					</div>
					<h2 class="text-lg sm:text-xl font-semibold text-gray-900 mb-2">Process View</h2>
					<p class="text-sm sm:text-base text-gray-500 mb-5 sm:mb-6 leading-relaxed">
						Open multiple processes side by side. Add a process to get started.
					</p>
					<button
						@click="showAddDialog = true"
						class="inline-flex items-center gap-2 px-4 sm:px-5 py-2.5 bg-gray-800 hover:bg-gray-900 active:bg-gray-950 text-white rounded-lg transition-colors font-medium text-sm shadow-md hover:shadow-lg"
					>
						<Icon icon="lucide:plus" class="w-4 h-4" />
						Add Process
					</button>
				</div>
			</div>
		</div>

		<!-- Add Process Dialog -->
		<Dialog v-model="showAddDialog" :options="{ title: 'Open a Process', size: isMobile ? 'xl' : 'md' }">
			<template #body-content>
				<div class="space-y-3">
					<!-- Search Input -->
					<div class="relative">
						<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
						<input
							ref="searchInputRef"
							v-model="searchQuery"
							type="text"
							placeholder="Search processes..."
							class="w-full pl-10 pr-3 py-2.5 sm:py-2 border border-gray-200 rounded-lg text-base sm:text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:border-gray-400"
							@input="debouncedSearch"
						/>
					</div>

					<!-- Process List -->
					<div class="max-h-[50vh] sm:max-h-80 overflow-y-auto border border-gray-100 rounded-lg -mx-1 sm:mx-0">
						<div v-if="loadingProcesses" class="p-8 text-center text-gray-400">
							<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>
							Loading processes...
						</div>
						<div v-else-if="filteredProcesses.length === 0" class="p-8 text-center text-gray-400">
							<Icon icon="lucide:search-x" class="w-8 h-8 mx-auto mb-2 text-gray-300" />
							No processes found
						</div>
						<div v-else>
							<button
								v-for="process in filteredProcesses"
								:key="process.name"
								@click="addProcess(process)"
								:disabled="isTabOpen(process.name)"
								:class="[
									'w-full flex items-center justify-between px-4 py-3.5 sm:py-3 text-left border-b border-gray-50 last:border-b-0 transition-colors',
									isTabOpen(process.name)
										? 'bg-gray-50 cursor-default'
										: 'hover:bg-gray-50 active:bg-gray-100 cursor-pointer'
								]"
							>
								<div class="min-w-0 flex-1">
									<div class="text-sm font-medium text-gray-900 truncate">{{ process.process_name }}</div>
									<div class="text-xs text-gray-400 mt-0.5">
										{{ process.diagram_count || 0 }} Process Map{{ process.diagram_count !== 1 ? 's' : '' }}
										<span v-if="process.process_owner_name" class="hidden sm:inline ml-2">· {{ process.process_owner_name }}</span>
									</div>
								</div>
								<div class="shrink-0 ml-3">
									<Badge v-if="isTabOpen(process.name)" theme="blue" label="Open" size="sm" />
									<Badge v-else :theme="getStatusTheme(process.status)" :label="process.status" size="sm" />
								</div>
							</button>
						</div>
					</div>

					<!-- Tab limit info -->
					<div v-if="openTabs.length >= MAX_TABS" class="flex items-start gap-2 rounded-lg px-3 py-2 text-xs bg-amber-50 border border-amber-200 text-amber-700">
						<Icon icon="lucide:alert-triangle" class="w-4 h-4 shrink-0 mt-0.5" />
						<span>Maximum {{ MAX_TABS }} processes can be open. Opening a new one will close the oldest inactive tab.</span>
					</div>
				</div>
			</template>
			<template #actions>
				<Button variant="subtle" @click="showAddDialog = false">Cancel</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from "vue";
import { useRouter, useRoute } from "vue-router";
import { frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import Editor from "@/views/Editor.vue";
import { useWindowSize } from "@/composables/useWindowSize";

const { isMobile } = useWindowSize();

const MAX_TABS = 5;
const STORAGE_KEY = "one_bpmn_process_view_tabs";

const router = useRouter();
const route = useRoute();

const openTabs = ref([]);
const activeTab = ref(null);
const showMobileTabMenu = ref(false);

// Add Process Dialog
const showAddDialog = ref(false);
const searchQuery = ref("");
const allProcesses = ref([]);
const loadingProcesses = ref(false);
const searchInputRef = ref(null);

let searchTimeout = null;

// Active tab label for mobile dropdown
const activeTabLabel = computed(() => {
	const tab = openTabs.value.find(t => t.name === activeTab.value);
	return tab ? (tab.process_name || tab.name) : "Select Process";
});

// Load tab state from localStorage
function loadTabState() {
	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		if (stored) {
			const parsed = JSON.parse(stored);
			if (Array.isArray(parsed.tabs) && parsed.tabs.length > 0) {
				openTabs.value = parsed.tabs;
				activeTab.value = parsed.active || parsed.tabs[0].name;
			}
		}
	} catch {
		// Ignore corrupt state
	}
}

// Persist tab state to localStorage
function saveTabState() {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({
			tabs: openTabs.value,
			active: activeTab.value,
		}));
	} catch {
		// Ignore storage errors
	}
}

// Watch for state changes and persist
watch([openTabs, activeTab], () => {
	saveTabState();
}, { deep: true });

onMounted(async () => {
	loadTabState();
	await loadProcesses();

	// If a process was passed via route param, open it
	if (route.params.process) {
		const processName = route.params.process;
		if (!isTabOpen(processName)) {
			// Find process info from loaded list, or create a minimal entry
			const processInfo = allProcesses.value.find(p => p.name === processName);
			if (processInfo) {
				addProcess(processInfo);
			} else {
				// Process not in list yet — add with minimal info
				addProcess({ name: processName, process_name: processName });
			}
		} else {
			activeTab.value = processName;
		}
	}
});

// Focus search input when dialog opens (skip on mobile — keyboard annoyance)
watch(showAddDialog, async (isOpen) => {
	if (isOpen) {
		searchQuery.value = "";
		await loadProcesses();
		if (!isMobile.value) {
			nextTick(() => {
				searchInputRef.value?.focus();
			});
		}
	}
});

async function loadProcesses() {
	loadingProcesses.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.list_processes",
		});
		if (Array.isArray(response)) {
			allProcesses.value = response;
		} else if (response && response.message) {
			allProcesses.value = response.message;
		} else if (response && Array.isArray(response.data)) {
			allProcesses.value = response.data;
		} else {
			allProcesses.value = [];
		}
	} catch (error) {
		console.error("Failed to load processes:", error);
		allProcesses.value = [];
	} finally {
		loadingProcesses.value = false;
	}
}

const filteredProcesses = computed(() => {
	if (!searchQuery.value.trim()) return allProcesses.value;
	const q = searchQuery.value.toLowerCase().trim();
	return allProcesses.value.filter(p =>
		(p.process_name && p.process_name.toLowerCase().includes(q)) ||
		(p.name && p.name.toLowerCase().includes(q))
	);
});

function debouncedSearch() {
	clearTimeout(searchTimeout);
	searchTimeout = setTimeout(() => {
		// Filtering is reactive via computed, no extra action needed
	}, 150);
}

function isTabOpen(name) {
	return openTabs.value.some(t => t.name === name);
}

function addProcess(process) {
	if (isTabOpen(process.name)) {
		// Just switch to it
		activeTab.value = process.name;
		showAddDialog.value = false;
		return;
	}

	// Enforce tab limit — LRU eviction
	if (openTabs.value.length >= MAX_TABS) {
		// Find the oldest tab that isn't the active one
		const evictIdx = openTabs.value.findIndex(t => t.name !== activeTab.value);
		if (evictIdx !== -1) {
			openTabs.value.splice(evictIdx, 1);
		}
	}

	openTabs.value.push({
		name: process.name,
		process_name: process.process_name || process.name,
	});
	activeTab.value = process.name;
	showAddDialog.value = false;

	// Update URL to reflect the active process
	router.replace({
		name: "ProcessView",
		params: { process: process.name },
	});
}

function switchTab(name) {
	if (activeTab.value === name) return;
	activeTab.value = name;

	// Move this tab to the end (most recently used) for LRU
	const idx = openTabs.value.findIndex(t => t.name === name);
	if (idx !== -1 && idx !== openTabs.value.length - 1) {
		const [tab] = openTabs.value.splice(idx, 1);
		openTabs.value.push(tab);
	}

	router.replace({
		name: "ProcessView",
		params: { process: name },
	});
}

function closeTab(name) {
	const idx = openTabs.value.findIndex(t => t.name === name);
	if (idx === -1) return;

	openTabs.value.splice(idx, 1);

	// If we closed the active tab, switch to the nearest remaining tab
	if (activeTab.value === name) {
		if (openTabs.value.length > 0) {
			// Pick the tab at the same index, or the last one
			const newIdx = Math.min(idx, openTabs.value.length - 1);
			activeTab.value = openTabs.value[newIdx].name;
			router.replace({
				name: "ProcessView",
				params: { process: activeTab.value },
			});
		} else {
			activeTab.value = null;
			router.replace({ name: "ProcessView" });
		}
	}
}

function getStatusTheme(status) {
	switch (status) {
		case "Active": return "green";
		case "Inactive": return "orange";
		default: return "gray";
	}
}
</script>

<style scoped>
/* Hide scrollbar on the tab container */
.no-scrollbar {
	-ms-overflow-style: none;
	scrollbar-width: none;
}
.no-scrollbar::-webkit-scrollbar {
	display: none;
}
</style>
