<template>
	<!-- Phases like CLARIFY or NO_MATCH carry no panel, no stage action and no
	     next step — their whole answer is the reply text, so the card renders
	     nothing rather than an empty shell above it. -->
	<CardShell v-if="hasContent" :title="title">
		<LuCrusherResultBody
			:panel="panel"
			:busy="busy"
			:confirmed="confirmed"
			:matches="matches"
			:doc="doc"
			:swimlanes="swimlanes"
			:scan="scan"
			:doctypes="doctypes"
			:hooks="hooks"
			:files="files"
			:topology="topology"
			:processes="processes"
			:task-processes="taskProcesses"
			:task-columns="TASK_COLUMNS"
			:prompt-processes="promptProcesses"
			:copied-index="copied"
			@quick-send="quickSend"
			@copy="copy"
		/>

		<!-- Confirm / request-changes, then the contextual next steps ── -->
		<Row v-if="stageActions.length && !confirmed" :gap="8">
			<ActionButton
				v-for="(a, i) in stageActions"
				:key="i"
				:label="a.label"
				:kind="i === 0 ? 'solid' : 'outline'"
				:disabled="busy"
				@press="quickSend(a.message)"
			/>
		</Row>
		<div v-else-if="confirmed" class="lcr-confirmed">✓ {{ confirmedLabel }}</div>

		<Stack v-if="suggestions.length" :gap="4">
			<span class="lcr-label">{{ __("What would you like to do next?") }}</span>
			<Row :gap="6">
				<ActionButton
					v-for="(s, i) in suggestions"
					:key="i"
					:label="`${s.icon} ${s.label}`"
					:disabled="busy"
					@press="quickSend(s.message)"
				/>
			</Row>
		</Stack>

		<template #expanded>
			<LuCrusherResultBody
				expanded
				:panel="panel"
				:busy="busy"
				:confirmed="confirmed"
				:matches="matches"
				:doc="doc"
				:swimlanes="swimlanes"
				:scan="scan"
				:doctypes="doctypes"
				:hooks="hooks"
				:files="files"
				:topology="topology"
				:processes="processes"
				:task-processes="taskProcesses"
				:task-columns="TASK_COLUMNS"
				:prompt-processes="promptProcesses"
				:copied-index="copied"
				@quick-send="quickSend"
				@copy="copy"
			/>
		</template>
	</CardShell>
</template>
<script setup>
// LuCrusherResultCard (WI-001678) = CardShell[Stack[…]] over the six panels
// lumina.js rendered by hand for onefm.lucrusher_result: process matches, a
// parsed Lucidchart document, a codebase scan, the topology proposal, the
// migration task list and the ProsAlly prompts. Which panel shows is decided
// by the payload's `intent`, exactly as handle_lucrusher_result decided it.
//
// Every button is a QUICK-SEND: it puts a literal sentence in the composer
// and sends it, which is all the legacy data-lcr-send buttons ever did. The
// sentences are copied verbatim from lumina.js — LuCrusher reads them as
// intent, so paraphrasing them would silently change the conversation.
//
// WI-003115: the panel body moved into LuCrusherResultBody.vue so the
// CardShell's #expanded slot can render the same body a second time,
// without the small card's 220px scroll cap, inside the large dialog.
// Stage actions and suggestions stay out of #expanded — the dialog is a
// read-only preview.
import { ref } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import Row from "../primitives/Row.vue";
import Stack from "../primitives/Stack.vue";
import LuCrusherResultBody from "./LuCrusherResultBody.vue";
import { useLuCrusherResult } from "./useLuCrusherResult.js";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});
const emit = defineEmits(["action"]);

const {
	__,
	TASK_COLUMNS,
	panel,
	confirmed,
	matches,
	doc,
	scan,
	topology,
	processes,
	taskProcesses,
	promptProcesses,
	title,
	swimlanes,
	doctypes,
	hooks,
	files,
	stageActions,
	confirmedLabel,
	suggestions,
	hasContent,
} = useLuCrusherResult(props);

const copied = ref(-1);

function quickSend(message) {
	emit("action", "quick-send", { message });
}

function copy(text, i) {
	navigator.clipboard.writeText(text || "").then(() => {
		copied.value = i;
		setTimeout(() => (copied.value = -1), 1500);
	});
}
</script>
<style scoped>
.lcr-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #7c7c7c; }
.lcr-confirmed { font-size: 12px; color: #278f5e; }
:global([data-theme="dark"]) .lcr-label { color: #808080; }
</style>
