<template>
	<Badge
		v-if="timestamp"
		theme="blue"
		size="sm"
		:label="relativeTime"
		class="whitespace-nowrap"
	/>
</template>

<script setup>
import { computed } from "vue"
import { Badge } from "frappe-ui"
import { dayjs } from "@/dayjs"

const props = defineProps({
	timestamp: {
		type: [String, Date, Number],
		default: null,
	},
})

// Uses the same dayjs + relativeTime plugin already loaded for the rest of
// the app (see @/dayjs and its use in VersionDiffDialog.vue), rather than
// hand-rolling another diff-to-string helper.
const relativeTime = computed(() => {
	if (!props.timestamp) {
		return ""
	}

	const synced = dayjs(props.timestamp)
	if (!synced.isValid()) {
		return "Invalid date"
	}

	const diffSec = dayjs().diff(synced, "second")
	if (diffSec < 60) {
		return "just now"
	}
	return synced.fromNow()
})
</script>
