<template>
	<Alert
		class="alloc-alert"
		title="Cost may be under-reported."
		type="warning"
	>
		<span class="text-xs">{{ note }}</span>
		<span
			v-for="model in models"
			:key="model"
			class="inline-block font-mono text-[11px] bg-amber-100 text-amber-900 rounded px-1.5 py-0.5 ml-1"
		>{{ model }}</span>
		<template #actions>
			<a
				class="text-xs underline whitespace-nowrap text-amber-900"
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

<style scoped>
/* The shared Alert is blue with an 18px title; the pricing gap is an amber one-liner. */
.alloc-alert :deep(.bg-surface-blue-1) {
	background: #fffbeb;
	border: 1px solid #fde68a;
	padding-top: 0.5rem;
	padding-bottom: 0.5rem;
}
.alloc-alert :deep(h3) {
	font-size: 12px;
	font-weight: 700;
	color: #92400e;
	line-height: 1.25rem;
}
.alloc-alert :deep(svg) {
	display: none;
}
.alloc-alert :deep(.ml-2) {
	margin-left: 0;
}
</style>
