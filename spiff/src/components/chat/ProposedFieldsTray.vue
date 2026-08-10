<template>
	<div class="tray">
		<div class="tray-head">
			<span class="tray-title">{{ __("Proposed values") }}</span>
			<span v-if="item.doneAction" class="tray-done">{{ doneText }}</span>
			<template v-else>
				<button v-if="canApply" class="tray-btn" :disabled="busy" @click="$emit('action', 'apply-fields', { fields: fields })">
					{{ __("Apply all") }}
				</button>
				<button class="tray-btn tray-btn--ghost" :disabled="busy" @click="$emit('action', 'dismiss')">
					{{ __("Dismiss") }}
				</button>
			</template>
		</div>
		<div v-for="(val, key) in fields" :key="key" class="tray-row">
			<span class="tray-key">{{ key }}</span>
			<span class="tray-val" :title="display(val)">{{ display(val) }}</span>
			<button
				v-if="canApply && !item.doneAction"
				class="tray-btn"
				:disabled="busy || applied[key]"
				@click="applyOne(key)"
			>
				{{ applied[key] ? __("Applied ✓") : __("Apply") }}
			</button>
		</div>
	</div>
</template>
<script setup>
// ProposedFieldsTray — the Form-surface layout's pinned hand-over strip
// (chat-surface-layout scope, 2026-08-10: "pinned tray" chosen over a full
// right pane). Renders the latest onefm.proposed_update payload docked above
// the composer, with per-field Apply so the designer can take some values
// and leave others. Same rule as every card: the tray renders and requests,
// the HOST applies.
//
// Per-field applies ride the normal card-action bus with a subset payload
// plus `partial: true`, which tells the panel NOT to retire the tray —
// only "Apply all" and "Dismiss" are terminal. The per-field applied state
// is optimistic; a host failure surfaces in the transcript via fail() but
// does not un-mark the chip (v1 trade-off, same as choice buttons).
import { computed, reactive } from "vue";

const props = defineProps({
	item: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	// Apply-capability handshake: false = the host has no form to apply
	// onto, so the tray shows the values read-only (Dismiss stays).
	canApply: { type: Boolean, default: true },
});
const emit = defineEmits(["action"]);

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const fields = computed(() => (props.item.value && props.item.value.fields) || {});
const applied = reactive({});

const doneText = computed(
	() =>
		({
			"apply-fields": __("Applied to the form"),
			dismiss: __("Dismissed — nothing was applied"),
		})[props.item.doneAction] || __("Done")
);

function display(val) {
	const text = typeof val === "string" ? val : JSON.stringify(val);
	return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

function applyOne(key) {
	applied[key] = true;
	emit("action", "apply-fields", { fields: { [key]: fields.value[key] }, partial: true });
}
</script>
<style scoped>
.tray { border: 1px solid var(--og2, #e2e2e2); border-radius: 10px; background: var(--sw, #fff); margin: 0 14px; font-size: 12px; }
.tray-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--og1, #ededed); }
.tray-title { font-weight: 600; color: var(--ig6, #525252); margin-right: auto; }
.tray-done { color: var(--ig5, #7c7c7c); font-style: italic; }
.tray-row { display: flex; align-items: center; gap: 10px; padding: 5px 10px; }
.tray-row + .tray-row { border-top: 1px solid var(--og1, #ededed); }
.tray-key { color: var(--ig5, #7c7c7c); font-family: ui-monospace, Menlo, monospace; flex: none; }
.tray-val { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ig8, #383838); }
.tray-btn { flex: none; height: 22px; padding: 0 8px; border: 1px solid var(--og2, #e2e2e2); border-radius: 6px;
	background: var(--sw, #fff); color: var(--ig8, #383838); cursor: pointer; font-size: 11px; }
.tray-btn:disabled { opacity: 0.6; cursor: default; }
.tray-btn--ghost { border-color: transparent; color: var(--ig5, #7c7c7c); }
</style>
