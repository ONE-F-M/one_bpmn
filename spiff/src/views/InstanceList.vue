<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<h1 class="text-xl font-semibold text-gray-900">Process Instances</h1>
			<a
				href="/desk/processa"
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

			<!-- Unified Context Filter -->
			<Popover>
				<template #target="{ togglePopover }">
					<Button
						variant="ghost"
						class="w-72 justify-between bg-gray-100 hover:bg-gray-200 border-none"
						@click="togglePopover"
					>

						<span class="truncate text-gray-700 font-normal">{{ contextPlaceholder }}</span>
						<template #suffix>
							<div class="flex items-center gap-1">
								<div 
									v-if="activeContext.doctype || activeContext.docname" 
									class="p-1 hover:bg-gray-300 rounded-full transition-colors"
									@click.stop="resetContext"
								>
									<FeatherIcon name="x-circle" class="w-3 h-3 text-gray-500" />
								</div>
								<FeatherIcon name="chevron-down" class="w-4 h-4 text-gray-400" />
							</div>
						</template>
					</Button>
				</template>
				<template #body="{ togglePopover }">
					<div class="p-2 w-72 bg-white shadow-2xl border border-gray-200 rounded-lg mt-1 z-50">
						<div v-if="activeContext.doctype" class="mb-2 px-2 py-1.5 bg-blue-50 text-blue-700 text-xs font-semibold rounded flex items-center justify-between">
							<span class="truncate">{{ activeContext.doctype.label }}</span>
							<FeatherIcon name="arrow-right" class="w-3 h-3 mx-1 opacity-50" />
							<span class="text-gray-500 font-normal">Select Document</span>
						</div>
						<TextInput
							v-model="contextQuery"
							:placeholder="activeContext.doctype ? 'Search document...' : 'Search DocType...'"
							class="mb-2"
							@input="debouncedFetch"
						>
							<template #prefix>
								<FeatherIcon name="search" class="w-4 h-4 text-gray-400" />
							</template>
						</TextInput>
						<div class="max-h-64 overflow-y-auto custom-scrollbar">
							<div
								v-for="opt in contextOptions"
								:key="opt.value"
								class="px-3 py-2 hover:bg-gray-100 cursor-pointer rounded text-sm text-gray-700 flex items-center justify-between group"
								@click="onContextSelect(opt, togglePopover)"
							>
								<span class="truncate">{{ opt.label }}</span>
								<FeatherIcon v-if="(activeContext.docname?.value === opt.value) || (!activeContext.docname && activeContext.doctype?.value === opt.value)" name="check" class="w-3 h-3 text-blue-500" />
							</div>
							<div v-if="contextOptions.length === 0" class="p-4 text-center text-gray-400 text-sm italic">
								No results found
							</div>
						</div>
					</div>
				</template>
			</Popover>

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
import { 
	frappeRequest, 
	Button, 
	TextInput,
	Popover,
	FormControl,
	Badge,
	Avatar,
	ListView,
	FeatherIcon
} from "frappe-ui"
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

// Unified Context State
const activeContext = ref({ doctype: null, docname: null })
const contextOptions = ref([])
const contextQuery = ref("")

const contextPlaceholder = computed(() => {
	if (!activeContext.value.doctype) return "Filter by Context..."
	if (!activeContext.value.docname) return `${activeContext.value.doctype.label}...`
	return `${activeContext.value.doctype.label}: ${activeContext.value.docname.label}`
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
	fetchContextOptions()
})

const debounceFilter = ref(null)
const fetchTimeout = ref(null)

function applyFilters() {
	if (debounceFilter.value) clearTimeout(debounceFilter.value)
	debounceFilter.value = setTimeout(() => {
		limitStart.value = 0
		loadInstances()
	}, 300)
}

function debouncedFetch() {
	if (fetchTimeout.value) clearTimeout(fetchTimeout.value)
	fetchTimeout.value = setTimeout(() => {
		fetchContextOptions(contextQuery.value)
	}, 300)
}

async function fetchContextOptions(query = "") {
	try {
		if (!activeContext.value.doctype) {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.utils.get_context_doctypes",
				params: { query }
			})
			contextOptions.value = response || []
		} else {
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.utils.get_context_documents",
				params: { 
					doctype: activeContext.value.doctype.value,
					query 
				}
			})
			contextOptions.value = response || []
		}
	} catch (error) {
		console.error("Failed to fetch context options:", error)
	}
}

function onContextSelect(option, togglePopover) {
	if (!option || !option.value) return

	if (!activeContext.value.doctype) {
		// Level 1 selection: DocType
		activeContext.value.doctype = option
		contextQuery.value = "" // Clear search for next level
		fetchContextOptions() // Load documents
		applyFilters() // Filter by DocType
		// We do NOT call togglePopover() here to keep it open
	} else {
		// Level 2 selection: Document
		activeContext.value.docname = option
		applyFilters() // Filter by specific document
		togglePopover() // Close the popover on final selection
	}
}

function resetContext() {
	activeContext.value = { doctype: null, docname: null }
	contextQuery.value = ""
	fetchContextOptions()
	applyFilters()
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
		
		// Apply context filters from unified state
		if (activeContext.value.doctype) {
			apiFilters.context_doctype = activeContext.value.doctype.value
		}
		if (activeContext.value.docname) {
			apiFilters.context_docname = activeContext.value.docname.value
		}

		// Use custom endpoint to fetch joined current_step data
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.instance_api.list_process_instances",
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
		instances.value = []
	} finally {
		loading.value = false
	}
}

function openInstance(name) {
	router.push({ name: "InstanceDetail", params: { instance: name } })
}

function getContextDocumentLink(row) {
	if (row.context_doctype && row.context_docname) {
		return `/desk/${row.context_doctype.toLowerCase().replace(/ /g, '-')}/${row.context_docname}`
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

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
	width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
	background: #f1f1f1;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
	background: #ddd;
	border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
	background: #ccc;
}
</style>

