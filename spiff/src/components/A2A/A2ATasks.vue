<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="bg-white px-4 sm:px-6 py-3 border-b flex flex-wrap gap-4 items-center">
			<FormControl
				v-model="filters.direction"
				type="select"
				:options="directionOptions"
				class="w-full sm:w-44"
				@change="loadTasks(0)"
			/>
			<FormControl
				v-model="filters.state"
				type="select"
				:options="stateOptions"
				class="w-full sm:w-48"
				@change="loadTasks(0)"
			/>
			<FormControl
				v-model="filters.agent"
				type="select"
				:options="taskAgentOptions"
				class="w-full sm:w-56"
				@change="loadTasks(0)"
			/>
			<Button
				v-if="filters.direction || filters.state || filters.agent"
				variant="ghost"
				@click="resetFilters"
			>
				Clear filters
			</Button>
			<div class="ml-auto flex flex-wrap items-center gap-4">
				<span class="text-sm text-gray-600">{{ total }} tasks</span>
				<A2APageSize v-model="pageLength" @change="changeTaskPageSize" />
			</div>
		</div>
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[56rem] text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Direction</th>
							<th
								class="px-4 py-2"
								title="The agent or caller that asked for this work"
							>
								Delegated by
							</th>
							<th class="px-4 py-2" title="The agent doing the work">Handled by</th>
							<th class="px-4 py-2">State</th>
							<th
								class="px-4 py-2"
								title="Nesting depth / total handoffs in this chain"
							>
								Depth / handoffs
							</th>
							<th class="px-4 py-2">Waiting on</th>
							<th class="px-4 py-2">Started</th>
						</tr>
					</thead>
					<tbody>
						<template v-for="t in a2aTasks" :key="t.name">
							<tr
								class="border-t cursor-pointer hover:bg-gray-50"
								@click="expandedTask = expandedTask === t.name ? '' : t.name"
							>
								<td class="px-4 py-2">
									<Badge :theme="directionTheme(t.direction)">{{
										t.direction
									}}</Badge>
								</td>
								<td class="px-4 py-2 text-gray-600">{{ initiator(t) }}</td>
								<td class="px-4 py-2 text-gray-600">
									{{ t.agent_configuration || "—" }}
								</td>
								<td class="px-4 py-2">
									<Badge :theme="stateTheme(t.state)">{{ t.state }}</Badge>
									<div
										v-if="t.error_message"
										class="text-xs text-red-600 mt-0.5"
									>
										{{ t.error_message }}
									</div>
								</td>
								<td class="px-4 py-2 text-gray-600">
									{{ t.delegation_depth }} / {{ t.handoff_count }}
								</td>
								<td class="px-4 py-2 text-gray-600 text-xs">
									<span v-if="t.pending_human_task">a person</span>
									<span v-else-if="t.next_poll_at && !isTerminal(t.state)">
										next check {{ t.next_poll_at }}
									</span>
									<span v-else class="text-gray-400">—</span>
								</td>
								<td class="px-4 py-2 text-gray-500 text-xs">{{ t.creation }}</td>
							</tr>
							<tr v-if="expandedTask === t.name" class="border-t bg-gray-50">
								<td colspan="7" class="px-4 sm:px-6 py-4">
									<div class="grid gap-3 md:grid-cols-2 text-sm">
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">
												What was asked
											</div>
											<div class="text-gray-800 whitespace-pre-wrap">
												{{ taskBrief(t) || "—" }}
											</div>
										</div>
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">
												Answer
											</div>
											<div class="text-gray-800 whitespace-pre-wrap">
												{{
													t.status_message ||
													t.error_message ||
													"no answer yet"
												}}
											</div>
										</div>
									</div>
									<div
										class="flex flex-wrap gap-x-6 gap-y-1 mt-4 text-xs text-gray-600"
									>
										<span>
											Task:
											<a
												:href="deskUrl('A2A Task', t.name)"
												target="_blank"
												class="text-blue-600 hover:underline"
												>{{ t.name }}</a
											>
										</span>
										<span v-if="t.instance">
											Doing the work:
											<router-link
												:to="`/processa/instances/${t.instance}`"
												class="text-blue-600 hover:underline"
												>{{ t.instance }}</router-link
											>
										</span>
										<span v-if="t.caller_instance">
											Waiting for it:
											<router-link
												:to="`/processa/instances/${t.caller_instance}`"
												class="text-blue-600 hover:underline"
												>{{ t.caller_instance }}</router-link
											>
										</span>
										<span v-if="t.task_execution_id"
											>Chain: {{ t.task_execution_id }}</span
										>
										<span>Started: {{ t.creation }}</span>
										<span v-if="t.completed_at"
											>Finished: {{ t.completed_at }}</span
										>
										<span v-if="t.deadline && !isTerminal(t.state)"
											>Deadline: {{ t.deadline }}</span
										>
									</div>
								</td>
							</tr>
						</template>
						<tr v-if="!a2aTasks.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								No tasks yet.
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<A2APager
				:start="start"
				:count="a2aTasks.length"
				:total="total"
				:page-length="pageLengthNum"
				@prev="prevTaskPage"
				@next="nextTaskPage"
			/>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Badge, Button, FormControl } from "frappe-ui";
import A2APageSize from "@/components/A2A/A2APageSize.vue";
import A2APager from "@/components/A2A/A2APager.vue";
import { useA2AList } from "@/composables/useA2AList";
import { A2A_API } from "@/utils/a2aApi";
import { deskUrl } from "@/utils/deskUrl";
import { directionTheme, initiator, isTerminal, stateTheme, taskBrief } from "@/utils/a2aFormat";

const props = defineProps({
	filterOptions: { type: Object, required: true },
});
const emit = defineEmits(["error", "count"]);

// Internal (one of our agents handing work to another) is the most common direction.
const directionOptions = [
	{ label: "All directions", value: "" },
	{ label: "Internal (same site)", value: "Internal" },
	{ label: "Inbound", value: "Inbound" },
	{ label: "Outbound", value: "Outbound" },
];

const stateOptions = [
	{ label: "All states", value: "" },
	{ label: "submitted", value: "submitted" },
	{ label: "working", value: "working" },
	{ label: "input-required", value: "input-required" },
	{ label: "completed", value: "completed" },
	{ label: "failed", value: "failed" },
	{ label: "canceled", value: "canceled" },
	{ label: "timed-out", value: "timed-out" },
];

const taskAgentOptions = computed(() => [
	{ label: "All agents", value: "" },
	...props.filterOptions.task_agents.map((a) => ({ label: a, value: a })),
]);

const filters = reactive({ direction: "", state: "", agent: "" });
const expandedTask = ref("");

const {
	rows: a2aTasks,
	total,
	start,
	loading,
	pageLength,
	pageLengthNum,
	load: loadTasks,
	prev: prevTaskPage,
	next: nextTaskPage,
	changeSize: changeTaskPageSize,
} = useA2AList({
	url: A2A_API + "list_tasks",
	rowsKey: "tasks",
	buildParams: () => ({
		direction: filters.direction || undefined,
		state: filters.state || undefined,
		agent_configuration: filters.agent || undefined,
	}),
	onError: (message) => emit("error", message),
});

watch(total, (n) => emit("count", n));

function resetFilters() {
	filters.direction = "";
	filters.state = "";
	filters.agent = "";
	loadTasks(0);
}

onMounted(() => loadTasks(0));
</script>
