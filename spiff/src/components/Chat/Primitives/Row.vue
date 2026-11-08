<template>
	<div class="prim-row" :style="{ gap: `${gap}px` }"><slot /></div>
</template>
<script setup>
// Layout primitive (WI-001673): a horizontal flex row.
defineProps({ gap: { type: Number, default: 8 } });
</script>
<style scoped>
.prim-row { display: flex; align-items: center; flex-wrap: wrap; min-width: 0; }
</style>
