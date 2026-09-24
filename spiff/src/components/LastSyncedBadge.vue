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

const props = defineProps({
	timestamp: {
		type: [String, Date, Number],
		default: null,
	},
})

const relativeTime = computed(() => {
	if (!props.timestamp) {
		return ""
	}

	const now = new Date()
	const syncDate = new Date(props.timestamp)

	if (isNaN(syncDate.getTime())) {
		return "Invalid date"
	}

	const diffMs = now.getTime() - syncDate.getTime()
	const diffSec = Math.floor(diffMs / 1000)
	const diffMin = Math.floor(diffSec / 60)
	const diffHours = Math.floor(diffMin / 60)
	const diffDays = Math.floor(diffHours / 24)
	const diffWeeks = Math.floor(diffDays / 7)

	if (diffSec < 60) {
		return "just now"
	} else if (diffMin < 60) {
		const mins = Math.max(1, diffMin)
		return `${mins} minute${mins > 1 ? "s" : ""} ago`
	} else if (diffHours < 24) {
		return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`
	} else if (diffDays < 7) {
		return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`
	} else if (diffWeeks < 4) {
		return `${diffWeeks} week${diffWeeks > 1 ? "s" : ""} ago`
	} else {
		const months = Math.floor(diffDays / 30)
		if (months < 12) {
			return `${months} month${months > 1 ? "s" : ""} ago`
		}
		const years = Math.floor(months / 12)
		return `${years} year${years > 1 ? "s" : ""} ago`
	}
})
</script>
