<template>
	<div class="prim-heading"><slot>{{ text }}</slot></div>
</template>
<script setup>
// Display primitive (WI-001673).
defineProps({ text: { type: String, default: "" } });
</script>
<style scoped>
.prim-heading { font-weight: 600; font-size: 12px; color: var(--acp-ink, #171717); }
</style>
