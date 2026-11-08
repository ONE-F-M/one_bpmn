<template>
	<div class="ai-agent-modal-overlay">
		<div :class="['ai-agent-modal', { 'ai-agent-modal--readonly': readonly }]">
			<!-- ============ LEFT: configuration form ============ -->
			<div class="modal-main">
				<div class="modal-header">
					<h3>
						{{ isSelector ? "Configure AI Task Selector" : "Configure AI Agent Task" }}
						<span v-if="readonly" class="readonly-badge">View only</span>
					</h3>
					<button class="close-btn" title="Close" @click="$emit('hide')">
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>

				<div class="modal-body">
					<fieldset class="field-gate" :disabled="readonly">
						<AgentConfigLinkedAgent />
						<AgentConfigCreatePanel />
						<AgentConfigRunSettings />
						<AgentConfigStaticContext />
						<AgentConfigScreening />
						<AgentConfigMemory />
					</fieldset>
				</div>

				<div class="modal-footer">
					<button class="btn-cancel" @click="$emit('close')">
						{{ readonly ? "Close" : "Cancel" }}
					</button>
					<button v-if="!readonly" class="btn-save" @click="save">Save</button>
				</div>
			</div>

			<AgentConfigAssistant v-if="!readonly" />
		</div>

		<!-- Standard error/notice dialog (frappe-ui) — replaces browser alert()s -->
		<Dialog v-model="notice.show" :options="{ title: notice.title }">
			<template #body-content>
				<p class="whitespace-pre-line text-p-base text-ink-gray-7">{{ notice.message }}</p>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { provide } from "vue";
import { Icon } from "@iconify/vue";
import { Dialog } from "frappe-ui";
import AgentConfigLinkedAgent from "@/components/AgentConfig/AgentConfigLinkedAgent/AgentConfigLinkedAgent.vue";
import AgentConfigCreatePanel from "@/components/AgentConfig/AgentConfigCreatePanel/AgentConfigCreatePanel.vue";
import AgentConfigRunSettings from "@/components/AgentConfig/AgentConfigRunSettings/AgentConfigRunSettings.vue";
import AgentConfigStaticContext from "@/components/AgentConfig/AgentConfigStaticContext/AgentConfigStaticContext.vue";
import AgentConfigScreening from "@/components/AgentConfig/AgentConfigScreening/AgentConfigScreening.vue";
import AgentConfigMemory from "@/components/AgentConfig/AgentConfigMemory/AgentConfigMemory.vue";
import AgentConfigAssistant from "@/components/AgentConfig/AgentConfigAssistant/AgentConfigAssistant.vue";
import {
	createAgentConfigContext,
	AGENT_CONFIG_KEY,
} from "@/composables/AgentConfig/useAgentConfigState";
import { useAgentConfigStaticContext } from "@/composables/AgentConfig/useAgentConfigStaticContext";
import { useAgentConfigModels } from "@/composables/AgentConfig/useAgentConfigModels";
import { useAgentConfigScreening } from "@/composables/AgentConfig/useAgentConfigScreening";
import { useAgentConfigLinked } from "@/composables/AgentConfig/useAgentConfigLinked";
import { useAgentConfigCreate } from "@/composables/AgentConfig/useAgentConfigCreate";
import { useAgentConfigAssistant } from "@/composables/AgentConfig/useAgentConfigAssistant";
import { useAgentConfigLoad } from "@/composables/AgentConfig/useAgentConfigLoad";
import { useAgentConfigSave } from "@/composables/AgentConfig/useAgentConfigSave";

const props = defineProps({
	element: { type: Object, required: true },
	modeler: { type: Object, required: true },
	// "agent" (AI Agent Task) or "selector" (AI Task Selector on an ad-hoc
	// subprocess). Selector mode hides fields the selector dispatch never
	// reads (backend, output variable, response format/schema, sampling,
	// retries) and writes only the selector attribute set on save.
	mode: { type: String, default: "agent" },
	// True when the map is open read-only: the form shows current values with
	// every field disabled (the <fieldset disabled> above), no Save button,
	// and the assistant chat (which can also apply edits onto the form) is
	// hidden entirely.
	readonly: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "hide"]);

const ac = createAgentConfigContext(props, emit);
provide(AGENT_CONFIG_KEY, ac);
useAgentConfigStaticContext(ac);
useAgentConfigModels(ac);
useAgentConfigScreening(ac);
useAgentConfigLinked(ac);
useAgentConfigCreate(ac);
useAgentConfigAssistant(ac);
useAgentConfigLoad(ac);
useAgentConfigSave(ac);

const { isSelector, notice, save } = ac;
</script>

<style scoped src="./AIAgentConfigModal.css"></style>

<style>
/* frappe-ui dialogs portal to <body> with no z-index of their own; this
   modal's overlay sits at z-index 1000, which would bury them. Dialogs are
   always the topmost surface. */
.dialog-overlay {
	z-index: 2000;
}
</style>
