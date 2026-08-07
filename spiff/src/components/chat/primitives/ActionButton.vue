<template>
	<button class="prim-btn" :class="`prim-btn--${kind}`" :disabled="disabled" @click="$emit('press')">
		<slot>{{ label }}</slot>
	</button>
</template>
<script setup>
// Interactive primitive (WI-001673): emits a named press, never mutates.
defineProps({
	label: { type: String, default: "" },
	kind: { type: String, default: "subtle" }, // solid | subtle | ghost | outline
	disabled: { type: Boolean, default: false },
});
defineEmits(["press"]);
</script>
<style scoped>
.prim-btn { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px;
	border: none; border-radius: 8px; font-size: 14px; cursor: pointer;
	background: #f3f3f3; color: #383838; }
.prim-btn--solid { background: #171717; color: #fff; }
.prim-btn--ghost { background: transparent; }
.prim-btn--outline { background: #fff; border: 1px solid #e2e2e2; }
.prim-btn:disabled { opacity: 0.55; cursor: default; }
@media (prefers-color-scheme: dark) {
	.prim-btn { background: #2b2b2b; color: #d4d4d4; }
	.prim-btn--solid { background: #f8f8f8; color: #0f0f0f; }
	.prim-btn--outline { background: #1c1c1c; border-color: #343434; }
}
</style>
