<template>
	<div class="prim-shell">
		<div class="prim-shell-head">
			<span class="prim-shell-title">{{ title }}</span>
			<slot name="head-extra" />
		</div>
		<div class="prim-shell-body"><slot /></div>
		<div v-if="$slots.actions" class="prim-shell-actions"><slot name="actions" /></div>
	</div>
</template>
<script setup>
// Container primitive (WI-001673): header + body + action bar. Every
// Document/Form card is CardShell[Heading, body, Row[actions]].
defineProps({ title: { type: String, default: "" } });
</script>
<style scoped>
.prim-shell { align-self: flex-start; width: 94%; background: var(--shell-bg, #fff);
	border: 1px solid var(--shell-line, #e2e2e2); border-radius: 10px; overflow: hidden; }
.prim-shell-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
	border-bottom: 1px solid #ededed; background: #f8f8f8; }
.prim-shell-title { font-size: 12px; font-weight: 600; color: #171717; }
.prim-shell-body { padding: 10px 12px; font-size: 13px; }
.prim-shell-actions { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #ededed; }
@media (prefers-color-scheme: dark) {
	.prim-shell { background: #1c1c1c; border-color: #343434; }
	.prim-shell-head { background: #232323; border-color: #232323; }
	.prim-shell-title { color: #f8f8f8; }
	.prim-shell-actions { border-color: #232323; }
}
</style>
