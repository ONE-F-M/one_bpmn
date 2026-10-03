<template>
	<CardShell :title="title" :done="done || !!doneAction" :done-text="doneText">
		<DiagramThumb :xml="value.bpmn_xml" />
		<template #actions>
			<ActionButton v-if="canApply" :label="applyLabel" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-diagram', value)" />
			<ActionButton :label="value.mode === 'pending_removal' ? 'No, keep it' : 'Discard'" kind="ghost"
				:disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
		<template #expanded>
			<div class="diagram-preview-expanded">
				<p v-if="value.summary" class="diagram-preview-expanded-summary">{{ value.summary }}</p>
				<DiagramThumb :xml="value.bpmn_xml" :height="expandedHeight()" large />
			</div>
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
	doneAction: { type: String, default: "" },
	surfaceType: { type: String, default: "" },
	artifactType: { type: String, default: "" },
	// Apply-capability handshake: false = no canvas in this host, preview only.
	canApply: { type: Boolean, default: true },
});
const doneText = computed(() => ({ "apply-diagram": "Applied — canvas updated", dismiss: "Discarded — the diagram is unchanged" })[props.doneAction] || (props.done ? "Done" : ""));
defineEmits(["action"]);
const title = computed(() => {
	const summary = props.value.summary ? ` — ${props.value.summary}` : "";
	if (props.value.mode === "pending_removal") return `Removes existing steps${summary}`;
	return `Diagram preview${summary}`;
});
const applyLabel = computed(() =>
	props.value.mode === "pending_removal" ? "Yes, apply changes" : "Apply to canvas"
);
// Read on each open, so the viewer matches the viewport at that moment.
const expandedHeight = () => Math.round(window.innerHeight * 0.7);
</script>
<style scoped>
.diagram-preview-expanded { display: flex; flex-direction: column; gap: 10px; }
.diagram-preview-expanded-summary { margin: 0; font-size: 13px; color: #383838; }
:global([data-theme="dark"]) .diagram-preview-expanded-summary { color: #d4d4d4; }
</style>
