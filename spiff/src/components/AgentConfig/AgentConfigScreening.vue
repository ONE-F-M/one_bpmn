<template>
	<!-- ============ Screening ============ -->
	<!-- Agent-level, like Memory below: what an agent may say is a property
               of the agent, not of the task that happens to call it.

               Rendered from the agent's OWN fields rather than a hard-coded list.
               15.1 has since added the output mode and it now appears here by
               itself, which is what this was built for; the injection mode
               will do the same. Labels, options and the explanatory
               text all come from the doctype, so there is nothing here to drift
               out of step with what the field actually accepts. -->
	<template v-if="!isSelector && form.aiAgentConfig && screeningControls.length">
		<!-- Grouped by what the control actually does. The throttle is
                 agent-owned like the screens, but it limits how OFTEN someone
                 may talk to the agent rather than what may pass — filing it
                 under "Screening" would misdescribe it. -->
		<template v-for="g in controlGroups" :key="g.name">
			<div class="field-group-title">{{ g.name }}</div>
			<!-- Hidden when the control it hangs off is unticked, matching the
                   desk form. Otherwise the two forms disagree about what is in
                   effect: the freeze thresholds stayed visible here with rate
                   limiting off, reading as settings that do something. -->
			<div class="field-row" v-for="c in visibleIn(g)" :key="c.fieldname">
				<label>{{ c.label }}</label>
				<select v-if="c.fieldtype === 'Select'" v-model="c.value">
					<option v-for="o in c.options" :key="o" :value="o">{{ o }}</option>
				</select>
				<input
					v-else-if="c.fieldtype === 'Check'"
					type="checkbox"
					class="checkbox-input"
					:checked="c.value == 1"
					@change="c.value = $event.target.checked ? 1 : 0"
				/>
				<input
					v-else-if="c.fieldtype === 'Int'"
					type="number"
					min="0"
					v-model.number="c.value"
				/>
				<!-- The allow-list. A child table on the doctype, so it arrives as
                     plain names with the set of agents that could legitimately be
                     picked, and goes back the same way. Tick boxes rather than a
                     multi-select: the list is short, and seeing who is NOT on it
                     matters as much as seeing who is. -->
				<div v-else-if="c.fieldtype === 'Agent List'" class="agent-allow-list">
					<label v-for="choice in c.choices || []" :key="choice" class="agent-allow-row">
						<input
							type="checkbox"
							class="checkbox-input"
							:checked="(c.value || []).includes(choice)"
							@change="toggleAllowed(c, choice, $event.target.checked)"
						/>
						<span>{{ choice }}</span>
					</label>
					<span v-if="!(c.choices || []).length" class="field-hint">
						No other agent is exposed over A2A yet, so there is nobody to allow.
					</span>
					<span v-else-if="!(c.value || []).length" class="field-hint">
						Nobody is on the list, so this agent may not delegate to anyone.
					</span>
				</div>
				<input v-else type="text" v-model="c.value" />
				<span class="field-hint" v-if="c.description">{{ c.description }}</span>
			</div>
		</template>
		<p class="field-hint" style="margin-top: 6px">
			These are stored on the linked AI Agent Configuration and apply wherever this agent
			runs.
		</p>
	</template>
</template>

<script setup>
import { inject } from "vue";
import { AGENT_CONFIG_KEY } from "@/composables/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const { screeningControls, form, isSelector, toggleAllowed, visibleIn, controlGroups } = ac;
</script>

<style scoped src="@/components/AgentConfig/agentConfigModal.css"></style>
