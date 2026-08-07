<template>
	<CardShell :title="title" :done="done || !!doneAction" :done-text="doneText">
		<DiffView v-if="value.diff" :diff="value.diff" />
		<CodeBlock v-else :code="value.modified_script" />
		<template #actions>
			<ActionButton label="Apply to editor" kind="solid" :disabled="busy || done"
				@press="$emit('action', 'apply-script', value)" />
			<ActionButton label="Discard" kind="ghost" :disabled="busy || done" @press="$emit('action', 'dismiss')" />
		</template>
	</CardShell>
</template>
<script setup>
// ScriptDiffCard (WI-001673) = CardShell[Heading, DiffView|CodeBlock, Actions].
// Renders onefm.script_diff. Apply reaches the editor through the host.
import { computed } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import CodeBlock from "../primitives/CodeBlock.vue";
import DiffView from "../primitives/DiffView.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
	doneAction: { type: String, default: "" },
	surfaceType: { type: String, default: "" },
	artifactType: { type: String, default: "" },
});
const doneText = computed(() => ({ "apply-script": "Applied — editor updated", dismiss: "Discarded — the script is unchanged" })[props.doneAction] || (props.done ? "Done" : ""));
defineEmits(["action"]);
const title = computed(() => {
	const target = props.value.apply_target || props.value.suggested_name;
	return `Script change${target ? ` — ${target}` : ""}`;
});
</script>
