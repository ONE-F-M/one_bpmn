<!-- Processa home view -->
<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between gap-4">
			<h1 class="text-xl font-semibold text-gray-900 shrink-0">Processes</h1>
			<div class="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 min-w-0">
				<Icon icon="lucide:info" class="w-4 h-4 text-blue-500 shrink-0" />
				<p class="text-xs text-blue-800 leading-snug">
					Existing processes are shown here, and a new process cannot be added from this page.
					To add a new process, please do so through the
					<a
						href="/app/process"
						target="_blank"
						rel="noopener noreferrer"
						class="font-semibold underline hover:text-blue-900 transition-colors"
					>desk page</a>.
				</p>
			</div>
			<a
				href="/app/processa"
				class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors shrink-0"
			>
				Go to Desk
				<Icon icon="lucide:external-link" class="w-4 h-4" />
			</a>
		</header>

		<!-- Export Process Map chooser dialog (processes with multiple process maps) -->
		<Dialog v-model="showExportDialog" :options="{ title: 'Export Process Map' }">
			<template #body-content>
				<div class="space-y-2">
					<p class="text-sm text-gray-500 mb-3">Choose a process map to download:</p>
					<div
						v-for="d in exportDialogDiagrams"
						:key="d.name"
						role="button"
						tabindex="0"
						class="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-100 cursor-pointer focus:outline-none focus:ring-2 focus:ring-gray-400"
						@click="exportSingleDiagram(d)"
						@keydown.enter.prevent="exportSingleDiagram(d)"
						@keydown.space.prevent="exportSingleDiagram(d)"
					>
						<span class="text-sm text-gray-800">{{ d.model_name || d.title }}</span>
						<Icon icon="lucide:download" class="w-4 h-4 text-gray-500" />
					</div>
				</div>
			</template>
			<template #actions>
				<Button variant="subtle" @click="showExportDialog = false">Cancel</Button>
			</template>
		</Dialog>


		<!-- Content -->
		<main class="flex-1 p-6 overflow-auto">
			<!-- Search + Filter (Only show when there are processes or if filtering) -->
			<div
				v-if="processes.length > 0 || hasActiveFilters"
				class="mb-4 flex items-center justify-between gap-2"
			>
				<TextInput
					v-model="filterKeyword"
					placeholder="Search processes..."
					class="w-64"
				>
					<template #prefix>
						<Icon icon="lucide:search" class="w-4 h-4 text-gray-400" />
					</template>
				</TextInput>

				<ProcessFilter v-model="activeFilters" :owner-options="ownerOptions" />
			</div>

			<!-- Loading State -->
			<div v-if="loading" class="flex items-center justify-center h-64">
				<div class="text-gray-500">Loading...</div>
			</div>

			<!-- Empty State (No processes at all in system) -->
			<div v-else-if="processes.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
				<div class="text-gray-400 mb-4">
					<Icon icon="lucide:layout-grid" class="w-16 h-16 mx-auto" />
				</div>
				<h3 class="text-lg font-medium text-gray-900 mb-1">No Processes Found</h3>
				<p class="text-gray-500 mb-4">Create a Process in the system to start building BPMN Process Maps.</p>
				<a
					href="/app/process"
					class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-md hover:bg-gray-800 transition-all hover:scale-[1.02] shadow-md focus:outline-none focus:ring-2 focus:ring-gray-900 focus:ring-offset-2 mt-2"
				>
					Go to Process List
					<Icon icon="lucide:plus" class="w-4 h-4" />
				</a>
			</div>

			<!-- No Matching Processes State -->
			<div v-else-if="sortedProcesses.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
				<div class="text-gray-400 mb-4">
					<Icon icon="lucide:search" class="w-16 h-16 mx-auto text-gray-300" />
				</div>
				<h3 class="text-lg font-medium text-gray-900 mb-1">No Matching Processes</h3>
				<p class="text-gray-500 mb-4">Try adjusting your search query.</p>
			</div>

			<!-- Mobile Card Layout -->
			<div v-else-if="isMobile" class="space-y-2">
				<div
					v-for="process in displayedProcesses"
					:key="process.name"
					@click="openProcess(process.name)"
					class="bg-white rounded-lg shadow-sm p-4 flex items-center gap-3 active:bg-gray-50 transition-colors cursor-pointer"
				>
					<Icon
						v-if="editabilityMap[process.name]"
						icon="lucide:pencil"
						class="w-4 h-4 text-green-500 shrink-0"
					/>
					<Icon
						v-else
						icon="lucide:lock"
						class="w-4 h-4 text-gray-300 shrink-0"
					/>
					<div class="flex-1 min-w-0">
						<div class="text-sm font-medium text-gray-900 truncate">{{ process.process_name }}</div>
						<div class="text-xs text-gray-400 mt-0.5">{{ process.diagram_count || 0 }} Process Map{{ process.diagram_count !== 1 ? 's' : '' }}</div>
					</div>
					<Badge :theme="getStatusTheme(process.status)" :label="process.status" size="sm" />
					<button
						v-if="process.diagram_count > 0"
						@click.stop="exportProcess(process)"
						:disabled="exportingProcesses.has(process.name)"
						class="p-1.5 rounded hover:bg-gray-200 text-gray-500 transition-colors disabled:opacity-40 shrink-0"
						title="Export BPMN"
						aria-label="Export BPMN"
					>
						<Icon
							:icon="exportingProcesses.has(process.name) ? 'lucide:loader-2' : 'lucide:download'"
							:class="['w-4 h-4', exportingProcesses.has(process.name) ? 'animate-spin' : '']"
						/>
					</button>
				</div>
			</div>

			<!-- Desktop List View -->
			<div v-else class="bg-white rounded-lg shadow-sm">
				<ListView
					:columns="columns"
					:rows="displayedProcesses"
					:options="{
						onRowClick: (row) => openProcess(row.name),
						selectable: false,
						showTooltip: false,
						resizeColumn: false,
					}"
					row-key="name"
				>
					<template #cell="{ item, row, column }">
						<!-- Title column -->
						<template v-if="column.key === 'process_name'">
							<div class="flex items-center gap-2">
								<Icon
									v-if="editabilityMap[row.name]"
									icon="lucide:pencil"
									class="w-3.5 h-3.5 text-green-500 shrink-0"
									title="Editable — Active Process Implementation"
								/>
								<Icon
									v-else
									icon="lucide:lock"
									class="w-3.5 h-3.5 text-gray-300 shrink-0"
									title="Locked — No editable Process Implementation"
								/>
								<div>
									<div class="text-sm font-medium text-gray-900">{{ item }}</div>
									<div v-if="row.diagram_count" class="text-xs text-gray-400">
										{{ row.diagram_count }} Process Map{{ row.diagram_count !== 1 ? 's' : '' }}
									</div>
								</div>
							</div>
						</template>

						<!-- Process Owner column -->
						<template v-else-if="column.key === 'process_owner_name'">
							<div v-if="item" class="flex items-center gap-2">
								<Avatar :label="item" size="sm" />
								<span class="text-sm text-gray-600">{{ truncate(item, 35) }}</span>
							</div>
							<span v-else class="text-sm text-gray-400">-</span>
						</template>


						<!-- Status column -->
						<template v-else-if="column.key === 'status'">
							<Badge :theme="getStatusTheme(item)" :label="item" />
						</template>

						<!-- Last Modified column -->
						<template v-else-if="column.key === 'last_modified'">
							<span class="text-sm text-gray-500">{{ formatDateTime(item) }}</span>
						</template>

						<!-- Created column -->
						<template v-else-if="column.key === 'creation'">
							<span class="text-sm text-gray-500">{{ formatDate(item) }}</span>
						</template>

						<!-- Export/actions column -->
						<template v-else-if="column.key === 'actions'">
							<button
								v-if="row.diagram_count > 0"
								@click.stop="exportProcess(row)"
								:disabled="exportingProcesses.has(row.name)"
								class="p-1.5 rounded hover:bg-gray-200 text-gray-500 transition-colors disabled:opacity-40"
								title="Export Process Map as .bpmn file"
							>
								<Icon
									:icon="exportingProcesses.has(row.name) ? 'lucide:loader-2' : 'lucide:download'"
									:class="['w-4 h-4', exportingProcesses.has(row.name) ? 'animate-spin' : '']"
								/>
							</button>
							<span v-else class="text-xs text-gray-300">—</span>
						</template>

						<!-- Default -->
						<template v-else>
							<span class="text-sm text-gray-600">{{ item }}</span>
						</template>
					</template>
				</ListView>
			</div>
		</main>

		<!-- Pagination Footer (fixed at bottom) -->
		<div
			v-if="sortedProcesses.length > 0"
			class="shrink-0 border-t border-gray-200 bg-white px-6 py-3"
		>
			<ListFooter
				v-model="pageLength"
				:options="{
					rowCount: displayedProcesses.length,
					totalCount: sortedProcesses.length,
				}"
				@loadMore="visibleCount += pageLength"
			/>
		</div>
	</div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from "vue"
import { useRouter } from "vue-router"
import { frappeRequest, TextInput, ListFooter } from "frappe-ui"
import { Icon } from "@iconify/vue"
import ProcessFilter from "@/components/ProcessFilter.vue"
import { dayjs } from "@/dayjs"
import { downloadBpmn } from "@/utils/downloadBpmn"
import { useWindowSize } from "@/composables/useWindowSize"

const { isMobile } = useWindowSize()

// Export dialog state
const showExportDialog = ref(false)
const exportDialogDiagrams = ref([])
// Track in-flight exports per process so concurrent clicks work independently
const exportingProcesses = ref(new Set())

const router = useRouter()
const processes = ref([])
const loading = ref(true)
const filterKeyword = ref("")

// Filters: array of { field, operator, value } managed by the Filter popover
const activeFilters = ref([])

// Client-side pagination (mirrors HelpDesk's ListFooter behaviour)
const pageLength = ref(20)
const visibleCount = ref(20)

// Distinct process owners present in the loaded data, for the owner filter
const ownerOptions = computed(() => {
	const seen = new Map()
	for (const p of processes.value) {
		if (p.process_owner && !seen.has(p.process_owner)) {
			seen.set(p.process_owner, p.process_owner_name || p.process_owner)
		}
	}
	const opts = [...seen.entries()].map(([value, label]) => ({ label, value }))
	opts.sort((a, b) => a.label.localeCompare(b.label))
	return opts
})

const hasActiveFilters = computed(
	() => filterKeyword.value.trim().length > 0 || activeFilters.value.length > 0
)

// Reset pagination whenever the active filter set changes
watch([filterKeyword, activeFilters], () => {
	visibleCount.value = pageLength.value
}, { deep: true })

// Changing the page length resets the visible window
watch(pageLength, (val) => {
	visibleCount.value = val
})

// Process Implementation editability map: { processName: true/false }
const editabilityMap = ref({})

const filteredProcesses = computed(() => {
	if (!Array.isArray(processes.value)) return []
	let list = processes.value
	if (filterKeyword.value) {
		const query = filterKeyword.value.toLowerCase().trim()
		list = list.filter(p =>
			(p.process_name && p.process_name.toLowerCase().includes(query)) ||
			(p.name && p.name.toLowerCase().includes(query))
		)
	}
	for (const f of activeFilters.value) {
		if (!f.value) continue
		list = list.filter(p => {
			const matches = p[f.field] === f.value
			return f.operator === "not_equals" ? !matches : matches
		})
	}
	return list
})

const sortedProcesses = computed(() => {
	return [...filteredProcesses.value].sort((a, b) => {
		const dateA = dayjs(a.last_modified)
		const dateB = dayjs(b.last_modified)
		return dateB.isAfter(dateA) ? 1 : -1
	})
})

// Current page slice shown in the list
const displayedProcesses = computed(() =>
	sortedProcesses.value.slice(0, visibleCount.value)
)

// Column definitions for ListView
const columns = computed(() => [
	{
		label: "Title",
		key: "process_name",
		width: 3,
	},
	{
		label: "Process Owner",
		key: "process_owner_name",
		width: 1,
	},
	{
		label: "Status",
		key: "status",
		width: "120px",
	},
	{
		label: "Last Modified",
		key: "last_modified",
		width: "180px",
	},
	{
		label: "Created",
		key: "creation",
		width: "120px",
	},
	{
		label: "",
		key: "actions",
		width: "60px",
	},
])

onMounted(async () => {
	await loadProcesses()
})

async function loadProcesses() {
	loading.value = true
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.list_processes",
		})
		
		// Handle different response formats
		if (Array.isArray(response)) {
			processes.value = response
		} else if (response && response.message) {
			processes.value = response.message
		} else if (response && Array.isArray(response.data)) {
			processes.value = response.data
		} else {
			processes.value = []
		}

		// Bulk check editability for all processes
		await checkAllEditability()
	} catch (error) {
		console.error("Failed to load processes:", error)
	} finally {
		loading.value = false
	}
}

async function checkAllEditability() {
	if (processes.value.length === 0) return

	try {
		const processNames = processes.value.map(p => p.name)
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.editability.bulk_check_processes_editable",
			// POST so the (potentially large) process_names list travels in the
			// request body — as a GET query string it builds a multi-KB URL that
			// nginx rejects with 400 Bad Request.
			method: "POST",
			params: { process_names: JSON.stringify(processNames) },
		})

		const data = response.message || response
		const map = {}
		for (const [name, info] of Object.entries(data)) {
			map[name] = !!info.editable
		}
		editabilityMap.value = map
	} catch (error) {
		console.error("Failed to check process editability:", error)
		// Default to all locked on error
		const map = {}
		processes.value.forEach(p => { map[p.name] = false })
		editabilityMap.value = map
	}
}

function openProcess(name) {
	router.push({ name: "ProcessEditor", params: { process: name } })
}

// ---- Export helpers ----

async function exportSingleDiagram(diagram) {
	showExportDialog.value = false
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_model",
			params: { name: diagram.name },
		})
		const data = response.message || response
		if (data && data.bpmn_xml) {
			downloadBpmn(data.bpmn_xml, data.title || diagram.model_name || diagram.name)
		}
	} catch (err) {
		console.error("Failed to export diagram:", err)
	}
}

async function exportProcess(process) {
	if (!process.diagram_count) return
	exportingProcesses.value = new Set([...exportingProcesses.value, process.name])
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_diagrams",
			params: { process: process.name },
		})
		const data = response.message || response
		const diagrams = (data.diagrams || []).map((d) => ({ ...d, model_name: d.model_name || d.title }))

		if (diagrams.length === 1) {
			await exportSingleDiagram(diagrams[0])
		} else if (diagrams.length > 1) {
			exportDialogDiagrams.value = diagrams
			showExportDialog.value = true
		}
	} catch (err) {
		console.error("Failed to fetch diagrams for export:", err)
	} finally {
		// Remove this process from the in-flight set
		const next = new Set(exportingProcesses.value)
		next.delete(process.name)
		exportingProcesses.value = next
	}
}

function getStatusTheme(status) {
	switch (status) {
		case "Active":
			return "green"
		case "Inactive":
			return "orange"
		default:
			return "gray"
	}
}

function truncate(text, length) {
	if (!text) return ""
	return text.length > length ? text.substring(0, length) + "..." : text
}

function formatDate(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY")
}

function formatDateTime(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}
</script>
