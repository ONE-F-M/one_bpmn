<template>
	<!-- Phases like CLARIFY or NO_MATCH carry no panel, no stage action and no
	     next step — their whole answer is the reply text, so the card renders
	     nothing rather than an empty shell above it. -->
	<CardShell v-if="view.hasContent" :title="view.title">
		<LuCrusherResultBody :value="value" :busy="busy" capped @action="(...a) => $emit('action', ...a)" />
		<template v-if="view.panel" #expanded>
			<LuCrusherResultBody :value="value" :busy="busy" readonly />
		</template>
	</CardShell>
</template>
<script setup>
// LuCrusherResultCard (WI-001678) = CardShell[LuCrusherResultBody] over the
// six panels lumina.js rendered by hand for onefm.lucrusher_result: process
// matches, a parsed Lucidchart document, a codebase scan, the topology
// proposal, the migration task list and the ProsAlly prompts. Which panel
// shows is decided by the payload's `intent`, exactly as
// handle_lucrusher_result decided it — see luCrusherView.js.
//
// Every button is a QUICK-SEND: it puts a literal sentence in the composer
// and sends it, which is all the legacy data-lcr-send buttons ever did. The
// sentences are copied verbatim from lumina.js — LuCrusher reads them as
// intent, so paraphrasing them would silently change the conversation.
import { computed } from "vue";
import CardShell from "../primitives/CardShell.vue";
import LuCrusherResultBody from "./LuCrusherResultBody.vue";
import { deriveLuCrusherView } from "./luCrusherView";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});
defineEmits(["action"]);

const view = computed(() => deriveLuCrusherView(props.value));
</script>
