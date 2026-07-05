<template>
	<div class="w-1/3 flex flex-col bg-white overflow-hidden">
		<div class="px-4 h-10 border-b bg-gray-50/60 shrink-0 flex items-center gap-2">
			<Icon icon="lucide:play-circle" class="w-4 h-4 text-orange-500" />
			<span class="text-sm font-semibold text-gray-700">Pending Actions</span>
			<Badge
				v-if="actionableTasks.length"
				theme="orange"
				:label="String(actionableTasks.length)"
				size="sm"
				class="ml-auto"
			/>
		</div>
		<div class="flex-1 overflow-y-auto custom-scrollbar p-3">
			<!-- A background engine pass is running (task dispatch / AI decisions):
			     any Waiting rows below are about to change, so show progress instead -->
			<div v-if="engineBusy" class="text-center py-6">
				<div class="w-8 h-8 rounded-full bg-purple-50 flex items-center justify-center mx-auto mb-2">
					<Icon icon="lucide:loader" class="w-5 h-5 text-purple-500 animate-spin" />
				</div>
				<span class="text-sm text-gray-500">Process is running…</span>
				<p class="text-[11px] text-gray-400 mt-1">Executing tasks and AI decisions — this view updates automatically.</p>
			</div>
			<div v-else-if="actionableTasks.length > 0" class="space-y-2">
				<div
					v-for="task in actionableTasks"
					:key="task.task_id"
					class="border rounded-lg p-3 bg-white hover:shadow-sm transition-shadow"
				>
					<div class="font-semibold text-gray-800 text-[13px] mb-1">
						{{ task.task_name || task.task_id }}
					</div>
					<div class="text-[11px] text-gray-500 font-mono mb-2">
						Since {{ formatDateTime(task.started_at) }}
					</div>
					<div v-if="task.assigned_user || task.assigned_role" class="flex items-center gap-2 text-[11px] mb-2">
						<span v-if="task.assigned_user" class="flex items-center gap-1 bg-blue-50 text-blue-700 px-2 py-0.5 rounded">
							<Icon icon="lucide:user" class="w-3 h-3" /> {{ task.assigned_user }}
						</span>
						<span v-if="task.assigned_role" class="flex items-center gap-1 bg-purple-50 text-purple-700 px-2 py-0.5 rounded">
							<Icon icon="lucide:users" class="w-3 h-3" /> {{ task.assigned_role }}
						</span>
					</div>
					<div class="flex flex-wrap gap-1.5">
						<template v-if="getActionDetails(task).length">
							<button
								v-for="detail in getActionDetails(task)"
								:key="detail.action"
								@click="$emit('complete', task, detail)"
								:disabled="completingTask === task.task_id"
								class="px-2.5 py-1 text-[11px] font-semibold rounded border transition-colors"
								:class="actionButtonClass(detail.action)"
							>
								<span v-if="completingTask === task.task_id && completingAction === detail.action" class="flex items-center gap-1">
									<Icon icon="lucide:loader" class="w-3 h-3 animate-spin" /> Processing…
								</span>
								<span v-else>{{ detail.action }}</span>
							</button>
						</template>
						<button
							v-else
							@click="$emit('complete', task, null)"
							:disabled="completingTask === task.task_id"
							class="px-2.5 py-1 text-[11px] font-semibold rounded border bg-gray-100 hover:bg-gray-200 text-gray-700 border-gray-300 disabled:opacity-50"
						>
							<span v-if="completingTask === task.task_id" class="flex items-center gap-1">
								<Icon icon="lucide:loader" class="w-3 h-3 animate-spin" /> Processing…
							</span>
							<span v-else class="flex items-center gap-1">
								<Icon icon="lucide:check" class="w-3 h-3" /> Complete
							</span>
						</button>
					</div>
				</div>
			</div>
			<div v-else class="text-center py-6">
				<div class="w-8 h-8 rounded-full bg-green-50 flex items-center justify-center mx-auto mb-2">
					<Icon icon="lucide:check" class="w-5 h-5 text-green-500" />
				</div>
				<span class="text-sm text-gray-400">No pending actions</span>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Badge } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"
import { useCurrentUser } from "@/composables/useCurrentUser"

const props = defineProps({
	activeTasks: { type: Array, default: () => [] },
	completingTask: { type: String, default: null },
	completingAction: { type: String, default: null },
	engineBusy: { type: Boolean, default: false },
})

defineEmits(["complete"])

const { currentUser, currentRoles } = useCurrentUser()

// Filter to tasks the current user can act on
const actionableTasks = computed(() => {
	if (!props.activeTasks.length) return []
	const user = currentUser.value
	const roles = currentRoles.value

	// System Manager / Administrator see all
	if (roles.includes("System Manager") || roles.includes("Administrator")) {
		return props.activeTasks
	}
	return props.activeTasks.filter((task) => {
		if (!task.assigned_user && !task.assigned_role) return true
		if (task.assigned_user && task.assigned_user === user) return true
		if (task.assigned_role && roles.includes(task.assigned_role)) return true
		return false
	})
})

// Action detail parsing
function getActionDetails(task) {
	if (task.task_actions_detail && Array.isArray(task.task_actions_detail) && task.task_actions_detail.length > 0) {
		return task.task_actions_detail.filter((d) => d && d.action)
	}
	const raw = (task.task_actions || "").trim()
	if (!raw) return []
	if (raw.startsWith("[")) {
		try {
			const parsed = JSON.parse(raw)
			if (Array.isArray(parsed)) return parsed.filter((d) => d && d.action)
		} catch (_) {
			// fall through
		}
	}
	return raw
		.split(",")
		.map((a) => a.trim())
		.filter(Boolean)
		.map((a) => ({ action: a }))
}

// Button color based on action semantics
const APPROVE_KEYWORDS = ["approve", "approved", "accept", "yes", "confirm"]
const REJECT_KEYWORDS = ["reject", "rejected", "decline", "no", "deny", "refuse"]

function actionButtonClass(action) {
	const lower = action.toLowerCase()
	if (APPROVE_KEYWORDS.some((k) => lower.includes(k))) {
		return "bg-green-50 hover:bg-green-100 text-green-800 border-green-300 disabled:opacity-50"
	}
	if (REJECT_KEYWORDS.some((k) => lower.includes(k))) {
		return "bg-red-50 hover:bg-red-100 text-red-800 border-red-300 disabled:opacity-50"
	}
	return "bg-blue-50 hover:bg-blue-100 text-blue-800 border-blue-300 disabled:opacity-50"
}

function formatDateTime(d) {
	return d ? dayjs(d).format("DD-MM-YYYY hh:mm A") : "-"
}
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.02); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
</style>
