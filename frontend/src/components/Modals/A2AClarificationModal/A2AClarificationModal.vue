<template>
	<Dialog v-model="open" :options="{ title: 'Clarification', size: '2xl' }">
		<template #body-content>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else-if="row" class="flex flex-col gap-5 text-sm">
				<div class="flex flex-wrap items-center gap-2">
					<Badge :theme="clarificationTheme(row)">
						{{ clarificationLabel(row) }}
					</Badge>
					<span class="text-gray-900 font-medium">
						{{ row.agent_configuration || "An agent" }}
						→
						{{ row.owner_asked || "the document owner" }}
					</span>
					<span class="text-gray-400 text-xs">{{ row.name }}</span>
				</div>

				<div
					v-if="row.status === 'Awaiting Answer'"
					class="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3"
				>
					<div class="font-medium text-orange-900">Still waiting</div>
					<div class="text-orange-800 mt-0.5">
						The agent is paused on this and will not guess.
						<span v-if="row.escalated_at">
							It was escalated to
							{{ row.escalated_to || "the process owner" }} on
							{{ row.escalated_at }}.
						</span>
						<span v-else-if="row.reminded_at">
							A reminder went out on {{ row.reminded_at }}.
						</span>
					</div>
				</div>

				<div class="grid gap-4 md:grid-cols-2">
					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">What it is about</div>
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
						<div v-else class="text-gray-400">nothing linked</div>
					</div>
					<div>
						<div class="text-xs uppercase text-gray-400 mb-1">Timing</div>
						<div class="text-gray-700">
							<div>asked {{ row.asked_at || "—" }}</div>
							<div v-if="row.answered_at">
								answered {{ row.answered_at }}
								<span v-if="row.answered_by"> by {{ row.answered_by }} </span>
							</div>
						</div>
					</div>
				</div>

				<div>
					<div class="text-xs uppercase text-gray-400 mb-1">The question</div>
					<div class="text-gray-800 whitespace-pre-wrap">
						{{ row.question || "—" }}
					</div>
					<div v-if="row.interpretations" class="text-gray-600 mt-2 whitespace-pre-wrap">
						<i>Choosing between:</i> {{ row.interpretations }}
					</div>
				</div>

				<div v-if="row.answer">
					<div class="text-xs uppercase text-gray-400 mb-1">The answer</div>
					<div class="text-gray-800 whitespace-pre-wrap">{{ row.answer }}</div>
				</div>

				<div v-if="thread.length > 1">
					<div class="text-xs uppercase text-gray-400 mb-2">
						The whole exchange about this document
					</div>
					<div
						v-for="t in thread"
						:key="t.name"
						class="border-l-2 pl-3 mb-3"
						:class="t.name === row.name ? 'border-blue-400' : 'border-gray-200'"
					>
						<div class="text-xs text-gray-500">
							Round {{ t.round }} · {{ t.status }}
							<span v-if="t.answered_by">· answered by {{ t.answered_by }}</span>
						</div>
						<div class="text-gray-800">{{ t.question }}</div>
						<div v-if="t.answer" class="text-gray-600 mt-0.5">→ {{ t.answer }}</div>
					</div>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { Badge, Dialog } from "frappe-ui";
import { clarificationLabel, clarificationTheme } from "@/utils/a2aFormat";
import { deskUrl } from "@/utils/deskUrl";

defineProps({
	row: { type: Object, default: null },
	title: { type: String, default: "" },
	thread: { type: Array, default: () => [] },
	loading: { type: Boolean, default: false },
});
const open = defineModel({ type: Boolean, default: false });
</script>
