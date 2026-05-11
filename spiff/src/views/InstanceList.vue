<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<h1 class="text-xl font-semibold text-gray-900">Process Instances</h1>
			<a
				href="/app/processa"
				class="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
			>
				Go to Desk
				<Icon icon="lucide:external-link" class="w-4 h-4" />
			</a>
		</header>

		<!-- Toolbar / Filters -->
		<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center">
			<FormControl
				type="text"
				v-model="filters.process_model"
				placeholder="Filter by Process Model"
				class="w-64"
				@update:model-value="applyFilters"
			/>
			<FormControl
				type="select"
				v-model="filters.status"
				:options="statusOptions"
				class="w-48"
				@change="applyFilters"
			/>
			<!-- Configurable page size -->
			<div class="flex items-center gap-2 ml-auto">
				<span class="text-sm text-gray-600">Page Size:</span>
				<FormControl
					type="select"
					v-model="limitPageLength"
					:options="[
						{ label: '10', value: 10 },
						{ label: '20', value: 20 },
						{ label: '50', value: 50 },
					]"
					class="w-20"
					@change="changePageSize"
				/>
			</div>
		</div>

		<!-- Content -->
		<main class="flex-1 p-6 overflow-auto">
			<!-- Loading State -->
			<div v-if="loading" class="flex items-center justify-center h-64">
				<div class="text-gray-500">Loading instances...</div>
			</div>

			<!-- Empty State -->
			<div v-else-if="instances.length === 0" class="flex flex-col items-center justify-center h-64 text-center">
				<div class="text-gray-400 mb-4">
					<Icon icon="lucide:layout-list" class="w-16 h-16 mx-auto" />
				</div>
				<h3 class="text-lg font-medium text-gray-900 mb-1">No Instances Found</h3>
				<p class="text-gray-500 mb-4">Try adjusting your filters or start a new process.</p>
			</div>

			<!-- List View -->
			<div v-else class="bg-white rounded-lg shadow-sm flex flex-col">
				<ListView
					:columns="columns"
					:rows="instances"
					:options="{
						onRowClick: (row) => openInstance(row.name),
						selectable: false,
						showTooltip: false,
						resizeColumn: false,
					}"
					row-key="name"
				>
					<template #cell="{ item, row, column }">
						<!-- Process Model column -->
						<template v-if="column.key === 'process_model'">
							<span class="text-sm font-medium text-gray-900">{{ item || '-' }}</span>
						</template>

						<!-- Status column -->
						<template v-else-if="column.key === 'status'">
							<Badge :theme="getStatusTheme(item)" :label="item || 'Unknown'" />
						</template>

						<!-- Context Document link -->
						<template v-else-if="column.key === 'context_docname'">
							<a
								v-if="item"
								:href="getContextDocumentLink(row)"
								@click.stop
								class="text-sm text-blue-600 hover:underline truncate block"
								:title="`${row.context_doctype} - ${item}`"
							>
								{{ row.context_doctype }} - {{ item }}
							</a>
							<span v-else class="text-sm text-gray-400">-</span>
						</template>

						<!-- Initiated By / User fields -->
						<template v-else-if="column.key === 'initiated_by'">
							<div v-if="item" class="flex items-center gap-2">
								<Avatar :label="item" size="sm" />
								<span class="text-sm text-gray-600">{{ item }}</span>
							</div>
							<span v-else class="text-sm text-gray-400">-</span>
						</template>

						<!-- Started At / DateTime fields -->
						<template v-else-if="column.key === 'started_at'">
							<span class="text-sm text-gray-500">{{ formatDateTime(item) }}</span>
						</template>

						<!-- Default fallback -->
						<template v-else>
							<span class="text-sm text-gray-600">{{ item || '-' }}</span>
						</template>
					</template>
				</ListView>

				<!-- Pagination Controls -->
				<div class="px-6 py-4 border-t flex items-center justify-between text-sm">
					<div class="text-gray-600">
						Showing {{ limitStart + 1 }} to {{ limitStart + instances.length }} 
					</div>
					<div class="flex items-center gap-2">
						<Button 
							variant="outline" 
							:disabled="limitStart === 0" 
							@click="prevPage"
						>
							Previous
						</Button>
						<Button 
							variant="outline" 
							:disabled="instances.length < limitPageLength" 
							@click="nextPage"
						>
							Next
						</Button>
					</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from "vue"
import { useRouter } from "vue-router"
import { frappeRequest } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const router = useRouter()
const instances = ref([])
const loading = ref(true)

// Pagination state
const limitStart = ref(0)
const limitPageLength = ref(20)

// Filters state
const filters = ref({
	process_model: "",
	status: "",
})

const statusOptions = [
	{ label: "All Statuses", value: "" },
	{ label: "Active", value: "Active" },
	{ label: "Completed", value: "Completed" },
	{ label: "Errored", value: "Errored" },
	{ label: "Cancelled", value: "Cancelled" },
]

// Column definitions for ListView
const columns = computed(() => [
	{ label: "Process Model", key: "process_model", width: 1.5 },
	{ label: "Status", key: "status", width: "120px" },
	{ label: "Context Document", key: "context_docname", width: 2.5 },
	{ label: "Current Step", key: "current_step", width: 2 },
	{ label: "Started At", key: "started_at", width: "180px" },
	{ label: "Initiated By", key: "initiated_by", width: "180px" },
])

onMounted(async () => {
	await loadInstances()
})

const debounceFilter = ref(null)

function applyFilters() {
	if (debounceFilter.value) clearTimeout(debounceFilter.value)
	debounceFilter.value = setTimeout(() => {
		limitStart.value = 0
		loadInstances()
	}, 300)
}

function changePageSize() {
	limitStart.value = 0
	loadInstances()
}

function prevPage() {
	if (limitStart.value > 0) {
		limitStart.value = Math.max(0, limitStart.value - limitPageLength.value)
		loadInstances()
	}
}

function nextPage() {
	if (instances.value.length === limitPageLength.value) {
		limitStart.value += limitPageLength.value
		loadInstances()
	}
}

async function loadInstances() {
	loading.value = true
	try {
		// Build frappe API filters
		const apiFilters = {}
		if (filters.value.process_model) {
			apiFilters.process_model = ["like", `%${filters.value.process_model}%`]
		}
		if (filters.value.status) {
			apiFilters.status = filters.value.status
		}

		// Use custom endpoint to fetch joined current_step data
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.list_process_instances",
			method: "POST",
			params: {
				filters: JSON.stringify(apiFilters),
				limit_start: limitStart.value,
				limit_page_length: limitPageLength.value,
				order_by: "creation desc"
			}
		})
		
		instances.value = response || []
	} catch (error) {
		console.error("Failed to load instances:", error)
		// Provide an empty array on fail (such as Doctype not existing yet)
		instances.value = []
	} finally {
		loading.value = false
	}
}

function openInstance(name) {
	router.push({ name: "InstanceDetail", params: { instance: name } })
}

function getContextDocumentLink(row) {
	// Constructing a link back to ERPNext desk for now.
	if (row.context_doctype && row.context_docname) {
		return `/app/${row.context_doctype.toLowerCase().replace(/ /g, '-')}/${row.context_docname}`
	}
	return "#"
}

function getStatusTheme(status) {
	switch (status) {
		case "Completed": return "green"
		case "Active": return "blue"
		case "Errored": return "red"
		case "Cancelled": return "gray"
		default: return "gray"
	}
}

function formatDateTime(dateStr) {
	if (!dateStr) return ""
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}
</script>
