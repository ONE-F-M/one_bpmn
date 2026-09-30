<template>
	<CardShell :title="title" :done="done || !!doneAction" :done-text="doneText">
		<DiagramThumb :xml="value.bpmn_xml" />
		<template #actions>
			<ActionButton v-if="canApply" :label="applyLabel" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-diagram', value)" />
			<ActionButton :label="value.mode === 'pending_removal' ? 'No, keep it' : 'Discard'" kind="ghost"
				:disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
		<!-- WI-003126: the expanded dialog view. CardShell shows the expand
		     icon only because this slot is provided, and teleports it out
		     of the 420px docked pane so the diagram isn't clipped. -->
		<template #expanded>
			<div class="diagram-preview-expanded">
				<p v-if="value.summary" class="diagram-preview-expanded-summary">{{ value.summary }}</p>
				<!-- NavigatedViewer (already used by DiagramThumb) supports
				     pan and zoom out of the box — no extra wiring needed. -->
				<DiagramThumb :xml="value.bpmn_xml" :height="expandedHeight" large />
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
// The expanded dialog fills most of the viewport; size the viewer to match
// rather than the 180px chat thumbnail height.
const expandedHeight = computed(() => Math.round(window.innerHeight * 0.7));
</script>
