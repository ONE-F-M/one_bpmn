<template>
	<header class="bg-white border-b px-5 py-3 shrink-0 shadow-sm z-10">
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-3">
				<Button icon-left="arrow-left" variant="ghost" size="sm" @click="$router.push('/processa/instances')">Back</Button>
				<div class="h-5 w-px bg-gray-200"></div>
				<h1 v-if="details" class="text-base font-bold text-gray-900 font-mono">{{ details.name }}</h1>
				<span v-if="details" class="text-sm text-gray-400">·</span>
				<span v-if="details" class="text-sm text-gray-600 flex items-center gap-1">
					<Icon icon="lucide:package" class="w-3.5 h-3.5 text-gray-400" />
					{{ details.process_model }}
				</span>
			</div>
			<Badge v-if="details" :theme="statusTheme" :label="details.status || 'Unknown'" size="lg" />
		</div>
		<div v-if="details" class="flex items-center gap-6 mt-2 text-[12px] text-gray-500">
			<div class="flex items-center gap-1.5">
				<span class="tracking-wide font-bold text-gray-600">Context</span>
				<a v-if="details.context_docname" :href="contextLink" target="_blank" class="font-semibold text-blue-600 hover:underline flex items-center gap-1">
					<Icon icon="lucide:file-text" class="w-3 h-3" /> {{ details.context_docname }}
				</a>
				<span v-else class="text-gray-400 italic">None</span>
			</div>
			<div class="flex items-center gap-1.5">
				<span class="tracking-wide font-bold text-gray-600">Initiated by</span>
				<span class="text-gray-700 flex items-center gap-1">
					<Icon icon="lucide:user-circle" class="w-3.5 h-3.5 text-gray-400" /> {{ details.initiated_by || '-' }}
				</span>
			</div>
			<div class="flex items-center gap-1.5">
				<span class="tracking-wide font-bold text-gray-600">Started</span>
				<span class="font-mono text-gray-700 flex items-center gap-1">
					<Icon icon="lucide:calendar-clock" class="w-3.5 h-3.5 text-gray-400" /> {{ formatDateTime(details.started_at) }}
				</span>
			</div>
			<div v-if="details.completed_at" class="flex items-center gap-1.5">
				<span class="tracking-wide font-bold text-gray-600">Finished</span>
				<span class="font-mono text-gray-700 flex items-center gap-1">
					<Icon icon="lucide:calendar-check" class="w-3.5 h-3.5 text-green-500" /> {{ formatDateTime(details.completed_at) }}
				</span>
			</div>
		</div>
	</header>
</template>

<script setup>
import { computed } from "vue"
import { Badge, Button } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

const props = defineProps({
	details: { type: Object, default: null },
})

const STATUS_THEMES = { Completed: "green", Active: "blue", Errored: "red" }
const statusTheme = computed(() => STATUS_THEMES[props.details?.status] || "gray")

const contextLink = computed(() => {
	const d = props.details
	if (d?.context_doctype && d?.context_docname) {
		return `/desk/${d.context_doctype.toLowerCase().replace(/ /g, "-")}/${d.context_docname}`
	}
	return "#"
})

function formatDateTime(d) {
	return d ? dayjs(d).format("DD-MM-YYYY hh:mm A") : "-"
}
</script>
