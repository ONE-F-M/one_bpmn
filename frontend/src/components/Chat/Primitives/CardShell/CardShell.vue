<template>
	<div class="prim-shell">
		<div class="prim-shell-head">
			<span class="prim-shell-title">{{ title }}</span>
			<slot name="head-extra" />
			<button
				v-if="$slots.expanded"
				type="button"
				class="prim-shell-expand"
				:title="__('Open in larger window')"
				:aria-label="__('Open in larger window')"
				@click="open = true"
			>
				<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"
					stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
				</svg>
			</button>
		</div>
		<div class="prim-shell-body"><slot /></div>
		<div v-if="$slots.actions && !done" class="prim-shell-actions"><slot name="actions" /></div>
		<div v-if="done && doneText" class="prim-shell-done">✓ {{ doneText }}</div>

		<Teleport v-if="$slots.expanded" to="body">
			<div v-if="open" class="prim-shell-scrim" @click.self="open = false">
				<div class="prim-shell-window" role="dialog" aria-modal="true" :aria-label="title">
					<div class="prim-shell-window-head">
						<span class="prim-shell-window-title">{{ title }}</span>
						<button type="button" class="prim-shell-expand" :title="__('Close')" :aria-label="__('Close')"
							@click="open = false">
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"
								stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<path d="M18 6 6 18M6 6l12 12" />
							</svg>
						</button>
					</div>
					<div class="prim-shell-window-body"><slot name="expanded" /></div>
				</div>
			</div>
		</Teleport>
	</div>
</template>
<script setup>
// Container primitive: header + body + action bar. Every
// Document/Form card is CardShell[Heading, body, Row[actions]]. Once a
// card's action is taken the buttons retire and a result line takes their
// place — a decision made cannot be re-made from a stale card.
//
// A card that fills #expanded gets a header button opening that content in
// a large read-only window; its actions stay on the small card. The window
// is a self-contained Teleport, not frappe-ui's Dialog: the one-ai bundle
// (Desk Chat button, /one-ai) ships no Tailwind, so Dialog renders
// unstyled there, and in the SPA App.vue pins .dialog-overlay to z-index 50,
// under DocuCanvas (2000) and LogixChat (9999). #expanded is mounted only
// while open, so a heavy body (bpmn-js viewer) never exists twice at rest.
import { onBeforeUnmount, ref, watch } from "vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	title: { type: String, default: "" },
	done: { type: Boolean, default: false },
	doneText: { type: String, default: "" },
});

const open = ref(false);

// Capture phase, and stopped: Escape closes this window only, not the
// Docu/Logix/Chat host underneath it.
function onKeydown(e) {
	if (e.key !== "Escape") return;
	e.preventDefault();
	e.stopImmediatePropagation();
	open.value = false;
}
watch(open, (isOpen) => {
	if (isOpen) window.addEventListener("keydown", onKeydown, true);
	else window.removeEventListener("keydown", onKeydown, true);
});
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown, true));
</script>
<style scoped>
.prim-shell { align-self: flex-start; width: 94%; background: var(--shell-bg, #fff);
	border: 1px solid var(--shell-line, #e2e2e2); border-radius: 10px; overflow: hidden; }
.prim-shell-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px;
	border-bottom: 1px solid #ededed; background: #f8f8f8; }
.prim-shell-title { font-size: 12px; font-weight: 600; color: #171717; flex: 1; min-width: 0; }
.prim-shell-body { padding: 10px 12px; font-size: 13px; }
.prim-shell-actions { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid #ededed; }
.prim-shell-done { padding: 10px 12px; border-top: 1px solid #ededed; font-size: 12px; color: #278f5e; }
.prim-shell-expand { display: grid; place-items: center; width: 24px; height: 24px; flex: none; padding: 0;
	border: none; border-radius: 6px; background: transparent; color: #7c7c7c; cursor: pointer; }
.prim-shell-expand:hover { background: #ededed; color: #171717; }
/* Above every chat host: SPA dialogs (50), one-ai scrim (1050), DocuCanvas
   (2000), LogixChat (9999) and its apply dialog (10000). */
.prim-shell-scrim { position: fixed; inset: 0; z-index: 10050; display: flex; align-items: center;
	justify-content: center; padding: 24px; background: rgba(23, 23, 23, 0.45); }
.prim-shell-window { display: flex; flex-direction: column; width: min(1280px, 96vw); height: 85vh;
	background: #fff; border-radius: 12px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18); overflow: hidden; }
.prim-shell-window-head { display: flex; align-items: center; gap: 8px; padding: 10px 16px;
	border-bottom: 1px solid #ededed; }
.prim-shell-window-title { flex: 1; min-width: 0; font-size: 14px; font-weight: 600; color: #171717; }
.prim-shell-window-body { flex: 1; min-height: 0; overflow: auto; padding: 16px; font-size: 13px; }
:global([data-theme="dark"]) .prim-shell { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .prim-shell-head { background: #232323; border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-title { color: #f8f8f8; }
:global([data-theme="dark"]) .prim-shell-actions { border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-expand { color: #999; }
:global([data-theme="dark"]) .prim-shell-expand:hover { background: #343434; color: #f8f8f8; }
:global([data-theme="dark"]) .prim-shell-window { background: #1c1c1c; }
:global([data-theme="dark"]) .prim-shell-window-head { border-color: #343434; }
:global([data-theme="dark"]) .prim-shell-window-title { color: #f8f8f8; }
</style>
