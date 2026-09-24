<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between gap-4">
			<div class="flex items-center gap-3">
				<Icon icon="lucide:cpu" class="w-6 h-6 text-gray-700" />
				<h1 class="text-xl font-semibold text-gray-900">Debug Info</h1>
			</div>
			<Button 
				v-if="!loading"
				@click="refreshData"
				:disabled="loading"
				variant="subtle"
				class="flex items-center gap-2"
			>
				<Icon icon="lucide:refresh-cw" :class="['w-4 h-4', loading ? 'animate-spin' : '']" />
				Refresh
			</Button>
		</header>

		<!-- Content -->
		<main class="flex-1 overflow-auto p-6">
			<div v-if="loading" class="flex items-center justify-center h-64">
				<div class="flex flex-col items-center gap-2">
					<Spinner />
					<p class="text-gray-500">Loading system information...</p>
				</div>
			</div>

			<div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 p-4">
				<div class="flex items-start gap-3">
					<Icon icon="lucide:alert-circle" class="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
					<div>
						<h3 class="font-semibold text-red-900 mb-1">Error Loading Debug Info</h3>
						<p class="text-red-800 text-sm">{{ error }}</p>
					</div>
				</div>
			</div>

			<div v-else class="space-y-6">
				<!-- System Status Panel -->
				<div class="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
					<div class="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
						<h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:activity" class="w-5 h-5 text-gray-700" />
							System Status
						</h2>
						<Badge 
							:label="statusData.status === 'healthy' ? 'Healthy' : 'Issue'" 
							:theme="statusData.status === 'healthy' ? 'green' : 'red'"
						/>
					</div>
					<div class="px-6 py-4 space-y-3">
						<div class="flex justify-between items-center py-2 border-b border-gray-100">
							<span class="text-sm font-medium text-gray-600">Current User</span>
							<span class="text-sm text-gray-900">{{ statusData.user }}</span>
						</div>
						<div class="flex justify-between items-center py-2 border-b border-gray-100">
							<span class="text-sm font-medium text-gray-600">Timestamp</span>
							<span class="text-sm text-gray-900">{{ formatDateTime(statusData.timestamp) }}</span>
						</div>
						<div class="flex justify-between items-center py-2 border-b border-gray-100">
							<span class="text-sm font-medium text-gray-600">Database</span>
							<div class="flex items-center gap-2">
								<Icon 
									:icon="statusData.database === 'connected' ? 'lucide:check-circle' : 'lucide:alert-circle'"
									:class="['w-4 h-4', statusData.database === 'connected' ? 'text-green-600' : 'text-red-600']"
								/>
								<span class="text-sm text-gray-900">{{ statusData.database }}</span>
							</div>
						</div>
						<div class="flex justify-between items-center py-2">
							<span class="text-sm font-medium text-gray-600">Redis</span>
							<div class="flex items-center gap-2">
								<Icon 
									:icon="statusData.redis.includes('connected') ? 'lucide:check-circle' : 'lucide:info'"
									:class="['w-4 h-4', statusData.redis.includes('connected') ? 'text-green-600' : 'text-gray-600']"
								/>
								<span class="text-sm text-gray-900">{{ statusData.redis }}</span>
							</div>
						</div>
					</div>
				</div>

				<!-- Environment Variables Panel -->
				<div class="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
					<div class="px-6 py-4 border-b border-gray-200">
						<h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:settings" class="w-5 h-5 text-gray-700" />
							Environment Variables
						</h2>
					</div>
					<div class="overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-gray-200 bg-gray-50">
									<th class="px-6 py-3 text-left font-semibold text-gray-700">Variable</th>
									<th class="px-6 py-3 text-left font-semibold text-gray-700">Value</th>
								</tr>
							</thead>
							<tbody>
								<tr 
									v-for="(value, key) in config.environment_variables"
									:key="key"
									class="border-b border-gray-100 hover:bg-gray-50 transition-colors"
								>
									<td class="px-6 py-3">
										<code class="text-xs font-mono text-gray-900 bg-gray-100 px-2 py-1 rounded">
											{{ key }}
										</code>
									</td>
									<td class="px-6 py-3">
										<code class="text-xs font-mono text-gray-700 break-all">
											{{ truncateValue(value) }}
										</code>
										<button
											v-if="value.length > 50"
											@click="toggleFullValue(key)"
											class="ml-2 text-xs text-blue-600 hover:text-blue-800 underline"
										>
											{{ expandedValues.has(key) ? 'hide' : 'show full' }}
										</button>
										<div v-if="expandedValues.has(key)" class="mt-2 p-2 bg-gray-100 rounded text-xs font-mono text-gray-700 break-all">
											{{ value }}
										</div>
									</td>
								</tr>
								<tr v-if="Object.keys(config.environment_variables).length === 0">
									<td colspan="2" class="px-6 py-4 text-center text-gray-500">
										No environment variables configured
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- System Info Panel -->
				<div v-if="config.system_info && !config.system_info.error" class="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
					<div class="px-6 py-4 border-b border-gray-200">
						<h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:hard-drive" class="w-5 h-5 text-gray-700" />
							System Information
						</h2>
					</div>
					<div class="px-6 py-4 space-y-3">
						<div class="grid grid-cols-2 gap-4">
							<div>
								<p class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Platform</p>
								<p class="text-sm text-gray-900">{{ config.system_info.platform }}</p>
							</div>
							<div>
								<p class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Release</p>
								<p class="text-sm text-gray-900">{{ config.system_info.platform_release }}</p>
							</div>
							<div>
								<p class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Python Version</p>
								<p class="text-sm text-gray-900 font-mono">{{ config.system_info.python_version }}</p>
							</div>
							<div>
								<p class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Processor</p>
								<p class="text-sm text-gray-900">{{ config.system_info.processor }}</p>
							</div>
						</div>
					</div>
				</div>

				<!-- Frappe Info Panel -->
				<div v-if="config.frappe_info && !config.frappe_info.error" class="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
					<div class="px-6 py-4 border-b border-gray-200">
						<h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:box" class="w-5 h-5 text-gray-700" />
							Frappe Information
						</h2>
					</div>
					<div class="px-6 py-4 space-y-3">
						<div class="flex justify-between items-center py-2 border-b border-gray-100">
							<span class="text-sm font-medium text-gray-600">Version</span>
							<span class="text-sm text-gray-900 font-mono">{{ config.frappe_info.version }}</span>
						</div>
						<div class="flex justify-between items-center py-2 border-b border-gray-100">
							<span class="text-sm font-medium text-gray-600">Current Site</span>
							<span class="text-sm text-gray-900">{{ config.frappe_info.current_site }}</span>
						</div>
						<div class="flex justify-between items-center py-2">
							<span class="text-sm font-medium text-gray-600">Sites Path</span>
							<code class="text-sm text-gray-700 font-mono bg-gray-100 px-2 py-1 rounded">{{ config.frappe_info.sites_path }}</code>
						</div>
					</div>
				</div>

				<!-- One BPMN Info Panel -->
				<div v-if="config.one_bpmn_info && !config.one_bpmn_info.error" class="bg-white rounded-lg border border-gray-200 overflow-hidden shadow-sm">
					<div class="px-6 py-4 border-b border-gray-200">
						<h2 class="text-lg font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:workflow" class="w-5 h-5 text-gray-700" />
							One BPMN Information
						</h2>
					</div>
					<div class="px-6 py-4">
						<div class="flex justify-between items-center py-2">
							<span class="text-sm font-medium text-gray-600">Module Path</span>
							<code class="text-sm text-gray-700 font-mono bg-gray-100 px-2 py-1 rounded break-all">{{ config.one_bpmn_info.module_path }}</code>
						</div>
					</div>
				</div>

				<!-- Info Notice -->
				<div class="rounded-lg border border-blue-200 bg-blue-50 p-4">
					<div class="flex items-start gap-3">
						<Icon icon="lucide:info" class="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
						<div>
							<p class="text-sm text-blue-900">
								This debug information is only visible to System Managers. It helps support engineers diagnose configuration and deployment issues quickly without requiring SSH access to the server.
							</p>
						</div>
					</div>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { frappeRequest, Spinner, Button, Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const loading = ref(true)
const error = ref(null)
const config = ref({
	environment_variables: {},
	system_info: {},
	frappe_info: {},
	one_bpmn_info: {},
})
const statusData = ref({
	status: "unknown",
	timestamp: null,
	user: "unknown",
	database: "unknown",
	redis: "unknown",
})
const expandedValues = ref(new Set())

onMounted(async () => {
	await refreshData()
})

async function refreshData() {
	loading.value = true
	error.value = null
	try {
		// Fetch configuration
		const configResponse = await frappeRequest({
			url: "/api/method/one_bpmn.api.debug_api.get_environment_configuration",
		})
		config.value = configResponse.message || configResponse

		// Fetch status
		const statusResponse = await frappeRequest({
			url: "/api/method/one_bpmn.api.debug_api.get_debug_status",
		})
		statusData.value = statusResponse.message || statusResponse
	} catch (err) {
		console.error("Failed to fetch debug info:", err)
		error.value = err.message || "Failed to load debug information. You may not have permission to access this data."
	} finally {
		loading.value = false
	}
}

function truncateValue(value, maxLength = 50) {
	if (typeof value !== "string") return String(value)
	if (value.length <= maxLength) return value
	return value.substring(0, maxLength) + "..."
}

function toggleFullValue(key) {
	if (expandedValues.value.has(key)) {
		expandedValues.value.delete(key)
	} else {
		expandedValues.value.add(key)
	}
	// Trigger reactivity
	expandedValues.value = new Set(expandedValues.value)
}

function formatDateTime(dateStr) {
	if (!dateStr) return "unknown"
	return dayjs(dateStr).format("DD-MM-YYYY HH:mm:ss")
}
</script>
