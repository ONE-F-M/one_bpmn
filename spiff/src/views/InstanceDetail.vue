<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<div class="flex items-center gap-4">
				<Button icon-left="arrow-left" variant="ghost" @click="router.push('/spiff/instances')">Back</Button>
				<h1 class="text-xl font-semibold text-gray-900">Instance Details</h1>
			</div>
			<div v-if="details">
				<Badge :theme="getStatusTheme(details.status)" :label="details.status || 'Unknown'" size="lg" />
			</div>
		</header>
		<main class="flex-1 p-6 overflow-auto">
			<div v-if="loading" class="flex justify-center flex-col items-center p-12 gap-4">
				<Icon icon="lucide:loader" class="w-8 h-8 text-gray-400 animate-spin" />
				<span class="text-gray-500">Loading details...</span>
			</div>
			<div v-else-if="details" class="max-w-4xl mx-auto space-y-6">
				<!-- Instance Info Card -->
				<div class="bg-white rounded-lg shadow-sm border p-6">
					<h2 class="text-lg font-medium text-gray-900 mb-4">{{ details.name }}</h2>
					<div class="grid grid-cols-2 md:grid-cols-4 gap-6">
						<div>
							<div class="text-xs text-gray-500 uppercase tracking-wide">Process Model</div>
							<div class="mt-1 text-sm font-medium">{{ details.process_model }}</div>
						</div>
						<div>
							<div class="text-xs text-gray-500 uppercase tracking-wide">Context Document</div>
							<div class="mt-1 text-sm">
								<a v-if="details.context_docname" :href="getContextDocumentLink()" class="text-blue-600 hover:underline">
									{{ details.context_doctype }} - {{ details.context_docname }}
								</a>
								<span v-else class="text-gray-400">-</span>
							</div>
						</div>
						<div>
							<div class="text-xs text-gray-500 uppercase tracking-wide">Initiated By</div>
							<div class="mt-1 text-sm">{{ details.initiated_by || '-' }}</div>
						</div>
						<div>
							<div class="text-xs text-gray-500 uppercase tracking-wide">Started At</div>
							<div class="mt-1 text-sm">{{ formatDateTime(details.started_at) }}</div>
						</div>
					</div>
				</div>

				<!-- Timeline Card -->
				<div class="bg-white rounded-lg shadow-sm border p-6">
					<h3 class="text-lg font-medium text-gray-900 mb-6">Timeline</h3>
					
					<div class="space-y-8 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-gray-200 before:to-transparent">

						<div v-if="activeTasks.length > 0" class="relative z-10 flex md:justify-center mb-[-1rem]">
							<span class="bg-blue-100 text-blue-700 text-xs font-bold uppercase tracking-wider py-1 px-3 rounded-full border border-blue-200 shadow-sm ml-10 md:ml-0">
								Currently Active
							</span>
						</div>

						<!-- Active Tasks Section (Top) -->
						<div v-for="task in activeTasks" :key="task.task_id" class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active">
							<div class="flex items-center justify-center w-10 h-10 rounded-full border-[3px] border-white bg-blue-100 text-blue-600 shadow-sm shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
								<Icon icon="lucide:loader" class="w-5 h-5 animate-spin" />
							</div>
							<div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-lg border border-blue-100 bg-blue-50 shadow-sm">
								<div class="flex items-center justify-between mb-1">
									<div class="font-semibold text-gray-900 text-sm">{{ task.task_name || task.task_id }}</div>
									<Badge theme="blue" label="Active" />
								</div>
								<div class="text-sm text-gray-600 mb-2">Started: {{ formatDateTime(task.started_at) }}</div>
								<!-- Assignee Details -->
								<div v-if="task.assigned_user || task.assigned_role" class="text-xs text-gray-700 bg-white p-2 text-sm rounded border border-blue-100 mt-2 space-y-1">
									<div v-if="task.assigned_user" class="flex gap-2">
										<span class="font-medium text-gray-500 w-12">User:</span>
										<span>{{ task.assigned_user }}</span>
									</div>
									<div v-if="task.assigned_role" class="flex gap-2">
										<span class="font-medium text-gray-500 w-12">Role:</span>
										<span>{{ task.assigned_role }}</span>
									</div>
								</div>
							</div>
						</div>

						<div v-if="logs.length > 0" class="relative z-10 flex md:justify-center mt-4 mb-[-1rem]">
							<span class="bg-gray-100 text-gray-600 text-xs font-bold uppercase tracking-wider py-1 px-3 rounded-full border shadow-sm ml-10 md:ml-0">
								History
							</span>
						</div>

						<!-- Activity Logs Section (Bottom) -->
						<div v-for="log in logs" :key="log.name" class="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group">
							<div class="flex items-center justify-center w-10 h-10 rounded-full border-[3px] border-white bg-gray-100 text-gray-500 shadow-sm shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 z-10">
								<Icon v-if="log.action === 'Completed'" icon="lucide:check" class="w-5 h-5 text-green-600" />
								<Icon v-else-if="log.action === 'Started'" icon="lucide:play" class="w-4 h-4 text-blue-600 ml-0.5" />
								<Icon v-else-if="log.action === 'Errored'" icon="lucide:alert-circle" class="w-5 h-5 text-red-600" />
								<Icon v-else icon="lucide:clock" class="w-5 h-5" />
							</div>
							<div class="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-4 rounded-lg border bg-white shadow-sm hover:shadow-md transition-shadow">
								<div class="flex items-center justify-between mb-1">
									<div class="font-semibold text-gray-900 text-sm">{{ log.task_name || log.task_id }}</div>
									<Badge :theme="getLogActionTheme(log.action)" :label="log.action" />
								</div>
								<div class="text-xs text-gray-500 mt-2 flex items-center gap-2">
									<Icon icon="lucide:calendar" class="w-3.5 h-3.5" />
									{{ formatDateTime(log.timestamp) }}
									<span v-if="log.user"> by {{ log.user }}</span>
								</div>
							</div>
						</div>
					</div>

					<!-- Load More Logs -->
					<div v-if="hasMoreLogs" class="mt-8 flex justify-center">
						<Button @click="loadLogs" :loading="logsLoading" variant="outline">Load Older Activity</Button>
					</div>
					<div v-else-if="logs.length === 0 && activeTasks.length === 0" class="mt-8 flex justify-center text-gray-500 text-sm">
						No activity found for this instance.
					</div>
					<div v-else class="mt-8 flex justify-center text-gray-400 text-xs uppercase tracking-widest font-medium">
						End of Timeline
					</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { frappeRequest, Badge, Button } from "frappe-ui"
import { dayjs } from "@/dayjs"
import { Icon } from "@iconify/vue"

const route = useRoute()
const router = useRouter()

const instanceId = computed(() => route.params.instance)

const loading = ref(true)
const details = ref(null)

const activeTasks = ref([])
const logs = ref([])

const limitStart = ref(0)
const limitPageLength = 20
const hasMoreLogs = ref(true)
const logsLoading = ref(false)

onMounted(async () => {
	await loadDetails()
	await loadLogs()
	loading.value = false
})

async function loadDetails() {
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_process_instance_details",
			method: "POST",
			params: { instance_id: instanceId.value }
		})
		details.value = res
		activeTasks.value = res.active_tasks || []
	} catch (e) {
		console.error("Failed to load instance details:", e)
	}
}

async function loadLogs() {
	if (logsLoading.value || !hasMoreLogs.value) return
	logsLoading.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_activity_logs",
			method: "POST",
			params: {
				instance_id: instanceId.value,
				limit_start: limitStart.value,
				limit_page_length: limitPageLength
			}
		})
		if (res && res.length > 0) {
			logs.value = [...logs.value, ...res]
			limitStart.value += res.length
			if (res.length < limitPageLength) {
				hasMoreLogs.value = false
			}
		} else {
			hasMoreLogs.value = false
		}
	} catch (e) {
		console.error("Failed to load instance logs:", e)
	} finally {
		logsLoading.value = false
	}
}

function getContextDocumentLink() {
	if (details.value?.context_doctype && details.value?.context_docname) {
		return `/app/${details.value.context_doctype.toLowerCase().replace(/ /g, '-')}/${details.value.context_docname}`
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

function getLogActionTheme(action) {
	switch (action) {
		case "Completed": return "green"
		case "Started": return "blue"
		case "Errored": return "red"
		case "Skipped": return "gray"
		default: return "gray"
	}
}

function formatDateTime(dateStr) {
	if (!dateStr) return "-"
	return dayjs(dateStr).format("DD-MM-YYYY hh:mm A")
}
</script>
