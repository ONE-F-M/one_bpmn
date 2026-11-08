<template>
	<svg
		viewBox="0 0 100 6"
		preserveAspectRatio="none"
		class="h-1.5"
		role="img"
		:aria-label="`${Math.round(share)}%`"
	>
		<rect
			width="100"
			height="6"
			rx="1"
			class="fill-gray-100"
		/>
		<rect
			:width="Math.min(Math.max(share, 0), 100)"
			height="6"
			rx="1"
			:fill="color"
		/>
	</svg>
</template>

<script setup>
defineProps({
	share: { type: Number, default: 0 },
	color: { type: String, default: "transparent" },
})
</script>
