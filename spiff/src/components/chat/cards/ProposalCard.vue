<template>
	<CardShell :title="isConfig ? 'Create this agent?' : 'Apply these values?'" :done="done || !!doneAction" :done-text="doneText">
		<KeyValueTable :rows="rows" />
		<template #actions>
			<ActionButton
				v-if="canApply"
				:label="isConfig ? 'Approve & create' : 'Apply to form'"
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
// payload shapes. It proposes; confirm-create relays the designer's approval
// into the conversation (the AGENT then calls its create tool), apply-fields
// is applied by the HOST (WI-001649 rule as amended).
import { computed } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import KeyValueTable from "../primitives/KeyValueTable.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
	doneAction: { type: String, default: "" },
	surfaceType: { type: String, default: "" },
	artifactType: { type: String, default: "" },
	// Apply-capability handshake: false = this host cannot apply/relay, so
	// the proposal is read-only (a chat approval typed in words still works).
	canApply: { type: Boolean, default: true },
});
const doneText = computed(() => ({ "confirm-create": "Approved — the assistant is creating it", "apply-fields": "Applied to the form", dismiss: "Dismissed — nothing was created" })[props.doneAction] || (props.done ? "Done" : ""));
defineEmits(["action"]);
const isConfig = computed(() => !!props.value.proposal);
const rows = computed(() => props.value.proposal || props.value.fields || {});
</script>
