<template>
	<Alert
		title="Cost may be under-reported"
		type="warning"
	>
		<span class="text-sm">{{ note }}</span>
		<span
			v-for="model in models"
			:key="model"
			class="inline-block font-mono text-xs bg-white/70 rounded px-1.5 py-0.5 ml-1"
		>{{ model }}</span>
		<template #actions>
			<a
				class="text-sm underline whitespace-nowrap"
				:href="link"
				target="_blank"
			>Add pricing on AI Model</a>
		</template>
	</Alert>
</template>

<script setup>
import { computed } from "vue"
import { Alert } from "frappe-ui"
import { pricingLink } from "@/utils/costAllocation"

const props = defineProps({
	models: { type: Array, required: true },
})

const note = computed(() => {
	const one = props.models.length === 1
	return `${props.models.length} ${one ? "model" : "models"} used in this period ${one ? "has" : "have"} no rate card, so ${one ? "its" : "their"} runs count as $0.00:`
})
const link = computed(() => pricingLink(props.models))
</script>

<style scoped></style>
