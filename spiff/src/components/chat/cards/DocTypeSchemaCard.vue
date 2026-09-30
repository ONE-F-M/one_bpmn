<template>
	<CardShell :title="title" :done="done || !!doneAction" :done-text="doneText">
		<FieldList :fields="fields" />
		<template #actions>
			<ActionButton v-if="canApply" label="Apply to builder" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-schema', value)" />
			<ActionButton label="Discard" kind="ghost" :disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
		<!-- WI-003118: expand into a bigger window (CardShell's shared #expanded
		     mechanism, WI-003115) with the field table at full width, plus the
		     raw doctype_ir as JSON \u2014 two stacked sections rather than tabs, so
		     both views are visible without extra clicks. -->
		<template #expanded>
			<div class="dtsc-expanded-section">
				<div class="dtsc-expanded-label">{{ __("Fields") }}</div>
				<FieldList class="dtsc-expanded-fields" :fields="fields" />
			</div>
			<div class="dtsc-expanded-section">
				<div class="dtsc-expanded-label">{{ __("JSON") }}</div>
				<pre class="dtsc-json">{{ JSON.stringify(value.doctype_ir, null, 2) }}</pre>
			</div>
		</template>
	</CardShell>
</template>
<script setup>
// DocTypeSchemaCard (WI-001673) = CardShell[Heading, FieldList, Actions].
// Renders onefm.doctype_schema; the host's loadIr() applies the IR.
import { computed } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import FieldList from "../primitives/FieldList.vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
	doneAction: { type: String, default: "" },
	surfaceType: { type: String, default: "" },
	artifactType: { type: String, default: "" },
	// Apply-capability handshake: false = no schema builder here, preview only.
	canApply: { type: Boolean, default: true },
});
const doneText = computed(() => ({ "apply-schema": "Applied — builder updated", dismiss: "Discarded — nothing was changed" })[props.doneAction] || (props.done ? "Done" : ""));
defineEmits(["action"]);
const fields = computed(() => (props.value.doctype_ir || {}).fields || []);
const title = computed(() => {
	const name = (props.value.doctype_ir || {}).name;
	return `Proposed fields${name ? ` — ${name}` : ""}`;
});
</script>
<style scoped>
.dtsc-expanded-section + .dtsc-expanded-section { margin-top: 16px; }
.dtsc-expanded-label { font-size: 11px; font-weight: 600; text-transform: uppercase;
	letter-spacing: .04em; color: #6b6b6b; margin-bottom: 6px; }
.dtsc-expanded-fields { width: 100%; }
.dtsc-json { margin: 0; max-height: 45vh; overflow: auto; padding: 10px 12px;
	background: #f8f8f8; border: 1px solid #ededed; border-radius: 8px;
	font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
	font-size: 12px; line-height: 1.5; white-space: pre; }
:global([data-theme="dark"]) .dtsc-expanded-label { color: #a3a3a3; }
:global([data-theme="dark"]) .dtsc-json { background: #1c1c1c; border-color: #343434; color: #e2e2e2; }
</style>
