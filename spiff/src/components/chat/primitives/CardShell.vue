<template>
	<div class="prim-shell">
		<div class="prim-shell-head">
			<span class="prim-shell-title">{{ title }}</span>
			<slot name="head-extra" />
			<!-- WI-003119: the shared expand mechanism. Any card that fills
			     #expanded gets a header button that opens the same content
			     at 7xl in a Dialog — one mechanism for every card, not one
			     per card that needs a bigger view. -->
			<button
				v-if="$slots.expanded"
				type="button"
				class="prim-shell-expand-btn"
				:title="__('Expand')"
				:aria-label="__('Expand')"
				@click="expanded = true"
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
					<path stroke-linecap="round" stroke-linejoin="round" d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
				</svg>
			</button>
		</div>
		<div class="prim-shell-body"><slot /></div>
		<div v-if="$slots.actions && !done" class="prim-shell-actions"><slot name="actions" /></div>
		<div v-if="done && doneText" class="prim-shell-done">✓ {{ doneText }}</div>

		<Dialog
			v-if="$slots.expanded"
			v-model="expanded"
			class="prim-shell-expand-dialog"
			:options="{ title, size: '7xl' }"
		>
			<template #body-content>
				<div class="prim-shell-expand-body"><slot name="expanded" /></div>
			</template>
		</Dialog>
	</div>
</template>
<script setup>
// Container primitive (WI-001673): header + body + action bar. Every
// Document/Form card is CardShell[Heading, body, Row[actions]]. Once a
// card's action is taken the buttons retire and a result line takes their
// place — a decision made cannot be re-made from a stale card.
//
// WI-003119: an optional #expanded slot + header button + Dialog. This is
// the ONE expand mechanism for chat cards — a card wanting a bigger view
// fills #expanded, it does not build its own dialog.
import { ref } from "vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	title: { type: String, default: "" },
	done: { type: Boolean, default: false },
	doneText: { type: String, default: "" },
});

const expanded = ref(false);
</script>
<style scoped>
.prim-shell { align-self: flex-start; width: 94%; background: var(--shell-bg, #fff);
	border: 1px solid var(--shell-line, #e2e2e2); border-radius: 10px; overflow: hidden; }
.prim-shell-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
	border-bottom: 1px solid #ededed; background: #f8f8f8; }
.prim-shell-title { font-size: 12px; font-weight: 600; color: #171717; }
.prim-shell-body { padding: 10px 12px; font-size: 13px; }
.prim-shell-actions { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #ededed; }
.prim-shell-done { padding: 10px 12px; border-top: 1px solid #ededed; font-size: 12px; color: #278f5e; }
.prim-shell-expand-btn { display: inline-flex; align-items: center; justify-content: center;
	margin-left: auto; width: 22px; height: 22px; padding: 0; border: none; border-radius: 6px;
	background: transparent; color: #7c7c7c; cursor: pointer; flex-shrink: 0; }
.prim-shell-expand-btn:hover { background: #ededed; color: #171717; }
.prim-shell-expand-body { max-height: 78vh; overflow: auto; }
:global([data-theme="dark"]) .prim-shell { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .prim-shell-head { background: #232323; border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-title { color: #f8f8f8; }
:global([data-theme="dark"]) .prim-shell-actions { border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-expand-btn { color: #999; }
:global([data-theme="dark"]) .prim-shell-expand-btn:hover { background: #2b2b2b; color: #f8f8f8; }
/* This Dialog can open from inside LogixCanvas's Teleport modal
   (views/Editor.vue) or from inside LogixChat's .lx-scrim (z-index 9999,
   with its own nested apply dialog at 10000). Both re-teleport to body,
   so a plain scoped rule cannot reach it — :global() plus a high z-index
   is required to sit above both hosts. */
:global(.prim-shell-expand-dialog) { z-index: 10050; }
</style>
