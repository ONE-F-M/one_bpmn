<template>
	<div
		v-if="conflict || status === 'paused'"
		class="absolute top-3 left-1/2 -translate-x-1/2 z-20 w-[min(36rem,calc(100%-1.5rem))]"
	>
		<div
			v-if="conflict"
			class="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 shadow-md"
		>
			<p class="flex-1 text-sm text-amber-900">
				{{ conflict.message }}
				Your changes are not saved yet.
			</p>
			<Button
				size="sm"
				@click="emit('load-latest')"
			>
				Load latest
			</Button>
			<Button
				size="sm"
				variant="solid"
				@click="emit('keep-mine')"
			>
				Keep mine
			</Button>
		</div>
		<p
			v-else
			class="rounded-lg border border-gray-200 bg-white px-4 py-2 text-xs text-gray-600 shadow-md"
		>
			Live sync is paused. {{ statusMessage }}
		</p>
	</div>
</template>

<script setup>
import { Button } from "frappe-ui"

defineProps({
	conflict: { type: Object, default: null },
	status: { type: String, default: "idle" },
	statusMessage: { type: String, default: "" },
})

const emit = defineEmits(["load-latest", "keep-mine"])
</script>

<style scoped>
</style>
