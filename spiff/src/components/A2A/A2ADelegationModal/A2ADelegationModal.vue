<template>
	<Dialog v-model="open" :options="{ title: 'Delegation', size: '2xl' }">
		<template #body-content>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else-if="row" class="flex flex-col gap-5 text-sm">
				<div class="flex flex-wrap items-center gap-2">
					<Badge :theme="delegationTheme(row.status)">
						{{ row.status }}
					</Badge>
					<span class="text-gray-900 font-medium">
						{{ row.delegating_agent || "someone" }}
						→
						{{ row.worker_agent || "an agent" }}
					</span>
					<span class="text-gray-400 text-xs">{{ row.name }}</span>
				</div>

				<div
					v-if="row.cancelled_by"
					class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3"
				>
					<div class="font-medium text-gray-900">Cancelled by a person</div>
					<div class="text-gray-700 mt-0.5">
						{{ row.cancelled_by }}
						<span v-if="row.cancelled_at"> on {{ row.cancelled_at }}</span
						>.
						<span v-if="row.error_message"> {{ row.error_message }}</span>
					</div>
				</div>

				<div
					v-if="row.stopped_reason && !row.cancelled_by"
					class="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3"
				>
					<div class="font-medium text-orange-900">
						Stopped at a limit — {{ limitLabel(row.stopped_reason) }}
					</div>
					<div class="text-orange-800 mt-0.5">
						<span v-if="row.limit_value">
							Reached {{ row.reached_value }} against a limit of
							{{ row.limit_value }}.
						</span>
						The work is not finished.
					</div>
					<div v-if="row.notified_user" class="text-xs text-orange-700 mt-1">
						{{ row.notified_user }} was told
						<span v-if="row.notified_at">on {{ row.notified_at }}</span
						>.
					</div>
				</div>

				<div class="grid gap-4 md:grid-cols-2">
					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">What it was for</div>
						<div v-if="row.reference_name" class="text-gray-800">
							<a
								:href="deskUrl(row.reference_doctype, row.reference_name)"
								target="_blank"
								class="text-blue-600 hover:underline"
							>
								{{ row.reference_name }}
							</a>
							<span class="text-gray-500"> · {{ row.reference_doctype }}</span>
							<div v-if="title" class="text-gray-600 mt-0.5">
								{{ title }}
							</div>
						</div>
						<div v-else class="text-gray-400">
							Nothing linked — the delegating run had no context document.
						</div>
					</div>
					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">The hand-off</div>
						<div v-if="row.a2a_task" class="text-gray-800">
							<a
								:href="deskUrl('A2A Task', row.a2a_task)"
								target="_blank"
								class="text-blue-600 hover:underline"
							>
								{{ row.a2a_task }}
							</a>
							<Badge v-if="task" :theme="stateTheme(task.state)" class="ml-2">
								{{ task.state }}
							</Badge>
						</div>
						<div v-else class="text-gray-400">no task row</div>
					</div>
				</div>

				<div>
					<div class="text-xs uppercase text-gray-400 mb-1">What was asked</div>
					<div class="text-gray-800 whitespace-pre-wrap">
						{{ row.instruction || "—" }}
					</div>
				</div>

				<div>
					<div class="text-xs uppercase text-gray-400 mb-1">What came back</div>
					<div class="text-gray-800 whitespace-pre-wrap">
						{{ answer }}
					</div>
				</div>
				<A2ADelegationActions
					:key="row.name"
					:row="row"
					@changed="emit('changed', $event)"
					@error="emit('error', $event)"
				/>
				<div class="grid gap-4 md:grid-cols-3 text-xs">
					<div>
						<div class="uppercase text-gray-400 mb-1">Counters</div>
						<div class="text-gray-700">
							depth {{ row.delegation_depth }} · hand-offs {{ row.handoff_count }} ·
							attempts {{ row.attempt_count || 1 }}
						</div>
					</div>
					<div>
						<div class="uppercase text-gray-400 mb-1">Timing</div>
						<div class="text-gray-700">
							<div>started {{ row.started_at || "—" }}</div>
							<div v-if="row.ended_at">ended {{ row.ended_at }}</div>
							<div v-if="task && task.deadline">deadline {{ task.deadline }}</div>
						</div>
					</div>
					<div>
						<div class="uppercase text-gray-400 mb-1">Instances</div>
						<div class="text-gray-700 flex flex-col">
							<router-link
								v-if="row.orchestrator_instance"
								:to="`/processa/instances/${row.orchestrator_instance}`"
								class="text-blue-600 hover:underline"
							>
								{{ row.orchestrator_instance }} (asked)
							</router-link>
							<router-link
								v-if="row.worker_instance"
								:to="`/processa/instances/${row.worker_instance}`"
								class="text-blue-600 hover:underline"
							>
								{{ row.worker_instance }} (doing)
							</router-link>
							<span
								v-if="!row.orchestrator_instance && !row.worker_instance"
								class="text-gray-400"
							>
								—
							</span>
						</div>
					</div>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed } from "vue";
import { Badge, Dialog } from "frappe-ui";
import A2ADelegationActions from "@/components/A2A/A2ADelegationActions/A2ADelegationActions.vue";
import { delegationTheme, limitLabel, stateTheme } from "@/utils/a2aFormat";
import { deskUrl } from "@/utils/deskUrl";

const props = defineProps({
	row: { type: Object, default: null },
	task: { type: Object, default: null },
	title: { type: String, default: "" },
	loading: { type: Boolean, default: false },
});
const emit = defineEmits(["changed", "error"]);
const open = defineModel({ type: Boolean, default: false });

const answer = computed(
	() =>
		props.task?.status_message ||
		props.row?.error_message ||
		props.task?.error_message ||
		"no answer recorded",
);
</script>
