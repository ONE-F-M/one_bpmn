<template>
	<CardShell :title="title">
		<FieldList :fields="fields" />
		<template #actions>
			<ActionButton label="Apply to builder" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-schema', value)" />
			<ActionButton label="Discard" kind="ghost" :disabled="busy || done" @press="$emit('action', 'dismiss')" />
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

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
const fields = computed(() => (props.value.doctype_ir || {}).fields || []);
const title = computed(() => {
	const name = (props.value.doctype_ir || {}).name;
	return `Proposed fields${name ? ` — ${name}` : ""}`;
});
</script>
