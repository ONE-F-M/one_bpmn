<template>
	<div class="prim-stack" :style="{ gap: `${gap}px`, flexDirection: horizontal ? 'row' : 'column' }">
		<slot />
	</div>
</template>
<script setup>
// Layout primitive (WI-001673): vertical by default, horizontal on demand.
defineProps({ gap: { type: Number, default: 8 }, horizontal: { type: Boolean, default: false } });
</script>
<style scoped>
.prim-stack { display: flex; min-width: 0; }
</style>
