<template>
	<CardShell :title="title">
		<DiagramThumb :xml="value.bpmn_xml" />
		<template #actions>
			<ActionButton :label="applyLabel" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-diagram', value)" />
			<ActionButton :label="value.mode === 'pending_removal' ? 'No, keep it' : 'Discard'" kind="ghost"
				:disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
	</CardShell>
</template>
<script setup>
// DiagramPreviewCard (WI-001673) = CardShell[Heading, DiagramThumb, Actions].
// Renders onefm.bpmn_preview — generated / modified / pending_removal in one
// card; the destructive-change confirm lives HERE, not in loose buttons.
// Deliberate behavior change: the canvas updates only on apply.
import { computed } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import DiagramThumb from "../primitives/DiagramThumb.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);
const title = computed(() => {
	const summary = props.value.summary ? ` — ${props.value.summary}` : "";
	if (props.value.mode === "pending_removal") return `Removes existing steps${summary}`;
	return `Diagram preview${summary}`;
});
const applyLabel = computed(() =>
	props.value.mode === "pending_removal" ? "Yes, apply changes" : "Apply to canvas"
);
</script>
