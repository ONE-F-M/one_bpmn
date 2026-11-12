<template>
	<!-- Linked AI Agent Configuration. Selecting
               one shows its current values in the fields below; at run time
               the configuration is authoritative for agent-level fields, and
               saving this dialog writes agent-level edits back to it. Tools
               are not imported — the toolkit stays this diagram's shapes. -->
	<div class="field-row">
		<label>
			Linked AI Agent Configuration
			<span class="hint">(required — raw provider setup is retired)</span>
		</label>
		<select v-model="form.aiAgentConfig" @change="onAgentConfigSelect">
			<option value="">-- None --</option>
			<option
				v-if="
					form.aiAgentConfig &&
					form.aiAgentConfig !== '__create__' &&
					!agentConfigs.some((c) => c.name === form.aiAgentConfig)
				"
				:value="form.aiAgentConfig"
			>
				{{ form.aiAgentConfig }}
			</option>
			<option v-for="c in agentConfigs" :key="c.name" :value="c.name">
				{{ c.name }}
			</option>
			<option value="__create__">＋ Create new…</option>
		</select>
		<span v-if="form.aiAgentConfig && form.aiAgentConfig !== '__create__'" class="field-hint">
			<span :class="['agent-status', agentStatusClass]" :title="'Deployment requires Live'">
				● {{ linkedAgentStatus || "checking…" }}
			</span>
			<!-- The Agent Creation Process re-checks an agent when
                   its record is saved — it waits on a Config Edited message. That
                   made "re-run the checks" mean "make an edit you do not want",
                   which is folklore, not an affordance. Same trigger, named, and
                   only where the process can still act: Live is already past it,
                   Retired is deliberate. -->
			<button
				v-if="['Draft', 'Needs Attention'].includes(linkedAgentStatus)"
				type="button"
				class="agent-rerun"
				:disabled="rerunning"
				:title="'Run the agent\'s validations and adversarial suite again'"
				@click="rerunChecks"
			>
				{{ rerunning ? "Re-running…" : "Re-run checks" }}
			</button>
			Prompt, provider, model and params resolve from this configuration when the process
			runs. Saving writes your edits back to it. Deploying this diagram requires the agent to
			be Live.
		</span>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { AGENT_CONFIG_KEY } from "@/composables/AgentConfig/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const {
	agentConfigs,
	linkedAgentStatus,
	rerunning,
	form,
	agentStatusClass,
	rerunChecks,
	onAgentConfigSelect,
} = ac;
</script>

<style scoped src="./AgentConfigLinkedAgent.css"></style>
