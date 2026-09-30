<template>
	<div class="prim-shell">
		<div class="prim-shell-head">
			<span class="prim-shell-title">{{ title }}</span>
			<slot name="head-extra" />
			<button
				v-if="$slots.expanded"
				class="prim-shell-expand"
				type="button"
				:title="__('Open in larger window')"
				@click="open = true"
			>
				<Icon icon="lucide:maximize-2" class="prim-shell-expand-icon" />
			</button>
		</div>
		<div class="prim-shell-body"><slot /></div>
		<div v-if="$slots.actions && !done" class="prim-shell-actions"><slot name="actions" /></div>
		<div v-if="done && doneText" class="prim-shell-done">✓ {{ doneText }}</div>

		<Dialog v-if="$slots.expanded" v-model="open" :options="{ title, size: '7xl' }">
			<template #body-content>
				<div class="h-[75vh] overflow-auto">
					<slot v-if="open" name="expanded" />
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
// WI-003115: a card may also offer an #expanded slot — the same body,
// rendered without the small card's size restrictions, inside a large
// Dialog. Explicit import because the one-ai IIFE bundle never runs
// main.js, so nothing registers Dialog globally there.
import { ref } from "vue";
import { Icon } from "@iconify/vue";
import { Dialog } from "frappe-ui";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	title: { type: String, default: "" },
	done: { type: Boolean, default: false },
	doneText: { type: String, default: "" },
});

const open = ref(false);
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
.prim-shell-expand { margin-left: auto; display: grid; place-items: center; width: 22px; height: 22px;
	border-radius: 6px; border: none; background: transparent; color: #7c7c7c; cursor: pointer; flex: none; }
.prim-shell-expand:hover { background: #ededed; color: #171717; }
.prim-shell-expand-icon { width: 14px; height: 14px; }
:global([data-theme="dark"]) .prim-shell { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .prim-shell-head { background: #232323; border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-title { color: #f8f8f8; }
:global([data-theme="dark"]) .prim-shell-actions { border-color: #232323; }
:global([data-theme="dark"]) .prim-shell-expand { color: #999; }
:global([data-theme="dark"]) .prim-shell-expand:hover { background: #343434; color: #f8f8f8; }
</style>
