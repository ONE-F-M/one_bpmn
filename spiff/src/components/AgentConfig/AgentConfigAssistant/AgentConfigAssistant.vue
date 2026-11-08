<template>
	<!-- ============ RIGHT: assistant chat panel ============ -->
	<!-- Hidden in read-only mode: the assistant can apply changes onto
           the form via card actions, which would bypass the fieldset's
           disabled state (that only blocks native form controls). A
           locked map must not be editable through this side door either. -->
	<div class="assistant-panel">
		<!-- One chat for both ways into this dialog. An AI Agent Task and an AI Task Selector
             open the same panel, on the same agent, over the same endpoint; the mode only
             changes what the turn is grounded with (server-side) and which fields the reply
             may recommend. The panel's own titlebar is the header in both. The assistant is
             always available: with no linked configuration yet it runs on its own
             credentials, so you can ask it to create the agent this task will link. -->
		<!-- The shared AgentChatPanel — one transport (the AG-UI endpoint),
               typed events, cards from the registry. Replies can never render
               as raw JSON: the assistant's reply shaper parses the contract
               server-side. A selector turn declares only apply-fields: it
               configures a SHAPE, so there is no agent record to create and no
               confirm-create card to honour. -->
		<AgentChatPanel
			ref="chatPanel"
			class="assistant-agui-panel"
			:agent-id="'ai_agent_assistant'"
			:conversation="assistantConversation"
			:context="assistantTurnContext"
			:context-provider="isSelector ? selectorTurnContext : null"
			:cards="cardRegistry"
			:apply-targets="isSelector ? ['apply-fields'] : ['apply-fields', 'confirm-create']"
			variant="docked"
			@conversation="(c) => (assistantConversation = c)"
			@card-action="onAssistantCardAction"
			@agent-event="onAssistantAgentEvent"
		/>
	</div>
</template>

<script setup>
import { inject } from "vue";
// agent mode chats through the shared panel + card registry.
import AgentChatPanel from "@/components/Chat/AgentChatPanel.vue";
import { cardRegistry } from "@/utils/cardRegistry";
import { AGENT_CONFIG_KEY } from "@/composables/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const {
	assistantConversation,
	isSelector,
	assistantTurnContext,
	selectorTurnContext,
	onAssistantCardAction,
	onAssistantAgentEvent,
	chatPanel,
} = ac;
</script>

<style scoped src="./AgentConfigAssistant.css"></style>
