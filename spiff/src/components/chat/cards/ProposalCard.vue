<template>
	<CardShell :title="isConfig ? 'Create this agent?' : 'Apply these values?'">
		<KeyValueTable :rows="rows" />
		<template #actions>
			<ActionButton
				:label="isConfig ? 'Create & link' : 'Apply to form'"
				kind="solid"
				:disabled="busy || done"
				@press="$emit('action', isConfig ? 'confirm-create' : 'apply-fields', rows)"
			/>
			<ActionButton label="Dismiss" kind="ghost" :disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
	</CardShell>
</template>
<script setup>
// ProposalCard (WI-001673) = CardShell[Heading, KeyValueTable, Row[Actions]].
// Renders onefm.proposed_config AND onefm.proposed_update — one card, two
// payload shapes. It proposes; the HOST creates/applies (WI-001649 rule).
import { computed } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import KeyValueTable from "../primitives/KeyValueTable.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
const isConfig = computed(() => !!props.value.proposal);
const rows = computed(() => props.value.proposal || props.value.fields || {});
</script>
