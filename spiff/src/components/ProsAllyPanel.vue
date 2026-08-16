<template>
	<div class="pa-wrap">
		<AgentChatPanel
			agent-id="prosally_agent"
			variant="docked"
			layout="conversation"
			:apply-targets="['apply-diagram']"
			:context="turnContext"
			:context-provider="withCanvasXml"
			:host-context-line="hostContextLine"
			:cards="cardRegistry"
			@choice="onChoice"
			@turn-complete="confirmedAction = ''"
			@card-action="onCardAction"
		>
			<template #header-actions>
				<button class="pa-close" :title="__('Close')" @click="$emit('close')">✕</button>
			</template>
		</AgentChatPanel>
	</div>
</template>

<script setup>
// ProsAllyPanel (WI-001675) — rebuilt on the shared AgentChatPanel +
// DiagramPreviewCard. 796 lines of bespoke chat became this wrapper: the
// panel owns transcript/composer/lifecycle (create on first message,
// end_chat_conversation on close, resume support); the wrapper owns only
// what is genuinely ProsAlly's — the editor context each turn carries and
// what "apply" means on this surface.
//
// Deliberate behavior change (WI-001671 decision): proposed diagrams arrive
// as onefm.bpmn_preview and render as a preview card — the canvas updates
// only when the user applies, never sight-unseen. The removal gate is the
// same card with mode=pending_removal; its confirm lives on the card.
//
// Greeting and composer placeholder come from the prosally_agent
// configuration (WI-001996); the process-specific line rides as
// host-context, exactly as the old hardcoded greeting composed it.
import { computed, ref } from "vue";
import { AgentChatPanel } from "@/components/chat";
import { cardRegistry } from "@/components/chat/cards/registry";

const props = defineProps({
	processName: { type: String, default: "" },
	diagramName: { type: String, default: "" },
	getCanvasXml: { type: Function, default: null },
});

const emit = defineEmits(["close", "bpmn-generated"]);

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

// CONFIRM intents: the map expects the approved action back as
// context.confirmed_action on the very next turn. The panel emits `choice`
// synchronously before sending, so staging it here reaches that turn.
const confirmedAction = ref("");

const hostContextLine = computed(() =>
	props.processName
		? `How would you like me to assist in defining the **${props.processName}** process on Processa?`
		: ""
);

const turnContext = computed(() => ({
	process_name: props.processName || "",
	diagram_name: props.diagramName || "",
	confirmed_action: confirmedAction.value || "",
}));

// The live canvas XML must be read per turn — the saved model may be stale
// while the designer edits (same rule the legacy panel followed).
async function withCanvasXml() {
	if (!props.getCanvasXml) return {};
	try {
		return { current_xml: ((await props.getCanvasXml()) || "").trim() };
	} catch (e) {
		return {};
	}
}

function onChoice({ option, actionIntent }) {
	confirmedAction.value = option.toLowerCase().startsWith("yes") ? actionIntent : "";
}

function onCardAction({ name, action, value }) {
	if (name === "onefm.bpmn_preview" && action === "apply-diagram" && value.bpmn_xml) {
		emit("bpmn-generated", value.bpmn_xml);
	}
}
</script>

<style scoped>
.pa-wrap { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.pa-wrap :deep(.acp) { height: 100%; }
.pa-close { border: none; background: none; color: #7c7c7c; cursor: pointer; font-size: 14px; margin-left: 8px; }
:global([data-theme="dark"]) .pa-close { color: #808080; }
</style>
