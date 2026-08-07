<template>
	<div class="prim-diff">
		<template v-if="rows.length">
			<div v-for="(row, i) in rows" :key="i" class="prim-diff-row" :class="`prim-diff--${row.type || 'ctx'}`">
				<pre class="prim-diff-cell prim-diff-left">{{ row.left ?? "" }}</pre>
				<pre class="prim-diff-cell prim-diff-right">{{ row.right ?? "" }}</pre>
			</div>
		</template>
		<pre v-else class="prim-diff-raw">{{ raw }}</pre>
	</div>
</template>
<script setup>
// Display primitive (WI-001673): split before/after view. Accepts the
// structured rows Logix's split-diff renderer produces, or a raw unified
// diff string as the graceful fallback.
import { computed } from "vue";
const props = defineProps({ diff: { type: [Array, String], default: () => [] } });
const rows = computed(() => (Array.isArray(props.diff) ? props.diff : []));
const raw = computed(() => (typeof props.diff === "string" ? props.diff : ""));
</script>
<style scoped>
.prim-diff { font-family: ui-monospace, Menlo, monospace; font-size: 11.5px;
	border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden; }
.prim-diff-row { display: grid; grid-template-columns: 1fr 1fr; }
.prim-diff-cell { margin: 0; padding: 2px 8px; white-space: pre; overflow-x: auto; }
.prim-diff--hunk .prim-diff-cell { background: #f3f3f3; color: #7c7c7c; }
.prim-diff--deleted .prim-diff-left, .prim-diff--changed .prim-diff-left { background: #ffe7e7; }
.prim-diff--added .prim-diff-right, .prim-diff--changed .prim-diff-right { background: #e4faeb; }
.prim-diff-raw { margin: 0; padding: 8px; white-space: pre-wrap; }
@media (prefers-color-scheme: dark) {
	.prim-diff { border-color: #343434; }
	.prim-diff--hunk .prim-diff-cell { background: #2b2b2b; color: #808080; }
	.prim-diff--deleted .prim-diff-left, .prim-diff--changed .prim-diff-left { background: #361515; }
	.prim-diff--added .prim-diff-right, .prim-diff--changed .prim-diff-right { background: #0a3f27; }
}
</style>
