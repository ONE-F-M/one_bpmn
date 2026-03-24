<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<h1 class="text-xl font-semibold text-gray-900">Processes</h1>
			<a
				href="/app/processa"
				class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
			>
				Go to Desk
				<Icon icon="lucide:external-link" class="w-4 h-4" />
			</a>
		</header>

		<!-- Export Diagram chooser dialog (multi-diagram processes) -->
		<Dialog v-model="showExportDialog" :options="{ title: 'Export Diagram' }">
			<template #body-content>
				<div class="space-y-2">
					<p class="text-sm text-gray-500 mb-3">Choose a diagram to download:</p>
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
			<!-- Loading State -->
			<div v-if="loading" class="flex items-center justify-center h-64">
				<div class="text-gray-500">Loading...</div>
			</div>

			<!-- Empty State -->
			<div v-else-if="processes.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
				<div class="text-gray-400 mb-4">
					<Icon icon="lucide:layout-grid" class="w-16 h-16 mx-auto" />
				</div>
				<h3 class="text-lg font-medium text-gray-900 mb-1">No Processes Found</h3>
				<p class="text-gray-500 mb-4">Create a Process in the system to start building BPMN diagrams.</p>
			</div>

			<!-- List View -->
			<div v-else class="bg-white rounded-lg shadow-sm">
				<ListView
					:columns="columns"
					:rows="processes"
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
							<div>
								<div class="text-sm font-medium text-gray-900">{{ item }}</div>
								<div v-if="row.diagram_count" class="text-xs text-gray-400">
									{{ row.diagram_count }} diagram{{ row.diagram_count !== 1 ? 's' : '' }}
								</div>
							</div>
						</template>

						<!-- Process Owner column -->
						<template v-else-if="column.key === 'process_owner_name'">
							<div v-if="item" class="flex items-center gap-2">
								<Avatar :label="item" size="sm" />
								<span class="text-sm text-gray-600">{{ truncate(item, 15) }}</span>
							</div>
							<span v-else class="text-sm text-gray-400">-</span>
						</template>

						<!-- Business Analyst column -->
						<template v-else-if="column.key === 'business_analyst_name'">
							<div v-if="item" class="flex items-center gap-2">
								<Avatar :label="item" size="sm" />
								<span class="text-sm text-gray-600">{{ truncate(item, 15) }}</span>
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
								title="Export diagram as .bpmn file"
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
	</div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue"
import { useRouter } from "vue-router"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import { downloadBpmn } from "@/utils/downloadBpmn"

// Export dialog state
const showExportDialog = ref(false)
const exportDialogDiagrams = ref([])
// Track in-flight exports per process so concurrent clicks work independently
const exportingProcesses = ref(new Set())

const router = useRouter()
const processes = ref([])
const loading = ref(true)

// Column definitions for ListView
const columns = computed(() => [
	{
		label: "Title",
		key: "process_name",
		width: 2,
	},
	{
		label: "Process Owner",
		key: "process_owner_name",
		width: "180px",
	},
	{
		label: "Business Analyst",
		key: "business_analyst_name",
		width: "180px",
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
			url: "/api/method/one_bpmn.api.list_processes",
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
	} catch (error) {
		console.error("Failed to load processes:", error)
	} finally {
		loading.value = false
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
			url: "/api/method/one_bpmn.api.get_process_model",
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
			url: "/api/method/one_bpmn.api.get_process_diagrams",
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
		case "Published":
			return "green"
		case "In Development":
			return "orange"
		case "Draft":
			return "blue"
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
