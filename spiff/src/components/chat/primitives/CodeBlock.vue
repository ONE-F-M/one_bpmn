<template>
	<pre class="prim-code"><code>{{ code }}</code></pre>
</template>
<script setup>
// Display primitive (WI-001673).
defineProps({ code: { type: String, default: "" } });
</script>
<style scoped>
.prim-code { font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; background: #f3f3f3;
	border-radius: 8px; padding: 8px 10px; overflow-x: auto; margin: 0; }
@media (prefers-color-scheme: dark) { .prim-code { background: #2b2b2b; } }
</style>
