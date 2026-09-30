<template>
	<div class="prim-shell">
		<div class="prim-shell-head">
			<span class="prim-shell-title">{{ title }}</span>
			<slot name="head-extra" />
			<button
				v-if="$slots.expanded"
				type="button"
				class="prim-shell-expand"
				:title="__('Expand')"
				:aria-label="__('Expand')"
				@click="expandedOpen = true"
			>
				<Icon icon="lucide:maximize-2" class="prim-shell-expand-icon" />
			</button>
		</div>
		<div class="prim-shell-body"><slot /></div>
		<div v-if="$slots.actions && !done" class="prim-shell-actions"><slot name="actions" /></div>
		<div v-if="done && doneText" class="prim-shell-done">✓ {{ doneText }}</div>

		<!-- WI-003115: shared expand mechanism. Any card that supplies an
		     #expanded slot gets the expand button above for free, opening
		     that slot's content in a full-size Dialog. Teleported to body,
		     like DocuCanvas's own overlay \u2014 see the z-index override below. -->
		<Dialog
			v-if="$slots.expanded"
			v-model="expandedOpen"
			class="prim-shell-expand-dialog"
			:options="{ title: title || __('Details'), size: '5xl' }"
		>
			<template #body-content>
				<div class="prim-shell-expanded-body">
					<slot name="expanded" />
				</div>
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
// WI-003115: an optional #expanded slot lets a card offer a bigger view
// (e.g. a full-width table plus the raw JSON) without every card having to
// build its own dialog. The expand button only appears when a card
// actually supplies that slot.
import { ref } from "vue";
import { Icon } from "@iconify/vue";
// Imported directly (not relying on global registration) because this
// component is shared by both the SPA (main.js registers Dialog globally)
// and the one-ai IIFE bundle (oneai-entry.js does not).
import { Dialog } from "frappe-ui";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	title: { type: String, default: "" },
	done: { type: Boolean, default: false },
	doneText: { type: String, default: "" },
});

const expandedOpen = ref(false);
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
.prim-shell-expand { display: inline-flex; align-items: center; justify-content: center;
	margin-left: auto; width: 22px; height: 22px; padding: 0; border: none; border-radius: 4px;
	background: transparent; color: #6b6b6b; cursor: pointer; flex: none; }
.prim-shell-expand:hover { background: #ededed; color: #171717; }
.prim-shell-expand-icon { width: 14px; height: 14px; }
.prim-shell-expanded-body { max-height: 70vh; overflow: auto; }
:global([data-theme="dark"]) .prim-shell { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .prim-shell-head { background: #232323; border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-title { color: #f8f8f8; }
:global([data-theme="dark"]) .prim-shell-actions { border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-expand { color: #a3a3a3; }
:global([data-theme="dark"]) .prim-shell-expand:hover { background: #2a2a2a; color: #f8f8f8; }
/* DocuCanvas's overlay (.dc-overlay) is a teleported, fixed-position
   scrim at z-index: 2000. This dialog also teleports to body, so its
   z-index must clear that scrim or an expand button opened from inside
   Docu would render underneath it. */
:global(.prim-shell-expand-dialog) { z-index: 2100; }
</style>
