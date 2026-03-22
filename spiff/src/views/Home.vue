<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<h1 class="text-xl font-semibold text-gray-900">Process</h1>
			<Button @click="router.push('/spiff/instances')">View Instances</Button>
		</header>

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
