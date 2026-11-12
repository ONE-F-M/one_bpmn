<template>
	<div class="prim-text"><slot>{{ text }}</slot></div>
</template>
<script setup>
// Display primitive. Named TextBlock: "Text" collides with DOM.
defineProps({ text: { type: String, default: "" } });
</script>
<style scoped>
.prim-text { font-size: 13px; min-width: 0; }
</style>
