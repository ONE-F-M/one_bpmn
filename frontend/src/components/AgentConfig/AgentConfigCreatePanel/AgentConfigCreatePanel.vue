<template>
	<!-- create a new AI Agent Configuration without leaving
               Processa. Inserted as Chat + Draft, so the AI Agent Creation
               Process takes it validate → provision → evaluate → Live on its
               own; the new agent is auto-linked on this shape. -->
	<div v-if="showCreateAgent" class="create-agent-panel">
		<div class="field-group-title">New AI Agent Configuration</div>
		<div class="field-row two-col">
			<div>
				<label>Agent Name <span class="hint">(required)</span></label>
				<input
					type="text"
					v-model="newAgent.agent_name"
					placeholder="e.g. Leave Summarizer"
				/>
			</div>
			<div>
				<label>Agent ID</label>
				<input
					type="text"
					v-model="newAgent.agent_id"
					:placeholder="scrubbedAgentId || 'auto from name'"
					@input="agentIdEdited = true"
				/>
			</div>
		</div>
		<div class="field-row two-col">
			<div>
				<label>Chat Mode Label <span class="hint">(required, unique)</span></label>
				<input
					type="text"
					v-model="newAgent.chat_mode_label"
					placeholder="e.g. Leave Summarizer"
				/>
			</div>
			<div>
				<label>AI Model <span class="hint">(provider follows the model)</span></label>
				<select v-model="newAgent.ai_model">
					<option value="">-- Pick a Model --</option>
					<option v-for="m in filteredCatalogModels" :key="m.name" :value="m.name">
						{{ modelLabel(m) }}
					</option>
				</select>
			</div>
		</div>
		<div class="field-row">
			<label
				>System Prompt
				<span class="hint"
					>(leave empty to auto-generate from the description)</span
				></label
			>
			<textarea v-model="newAgent.system_prompt" rows="3" />
		</div>
		<div class="field-row">
			<label>Description</label>
			<textarea
				v-model="newAgent.description"
				rows="2"
				placeholder="What this agent does — feeds prompt auto-generation"
			/>
		</div>
		<div class="field-row">
			<label
				>Sample Prompts
				<span class="hint">(optional — become the baseline eval suite)</span></label
			>
			<div v-for="(sp, i) in newAgent.sample_prompts" :key="i" class="sample-prompt-row">
				<input type="text" v-model="sp.prompt" placeholder="Sample user prompt" />
				<input
					type="text"
					v-model="sp.expected_behaviour"
					placeholder="Expected behaviour (optional)"
				/>
				<button
					type="button"
					class="close-btn"
					title="Remove"
					@click="newAgent.sample_prompts.splice(i, 1)"
				>
					✕
				</button>
			</div>
			<button
				type="button"
				class="btn-cancel"
				@click="newAgent.sample_prompts.push({ prompt: '', expected_behaviour: '' })"
			>
				+ Add sample prompt
			</button>
		</div>
		<div class="field-row">
			<label>Skills <span class="hint">(optional)</span></label>
			<div v-for="(s, i) in newAgent.ai_skills" :key="'newsk-' + i" class="static-row">
				<div class="static-row-head">
					<span class="static-row-inline-label">Skill</span>
					<select v-model="s.skill" class="static-row-cat">
						<option v-for="c in availableSkills" :key="c.name" :value="c.name">
							{{ c.name }}
						</option>
					</select>
					<span class="static-row-inline-label">Version pin</span>
					<input
						v-model="s.version_pin"
						type="text"
						placeholder="e.g. 1.0.0 (optional)"
						class="static-row-cat"
					/>
					<button
						type="button"
						class="close-btn"
						title="Remove"
						@click="newAgent.ai_skills.splice(i, 1)"
					>
						✕
					</button>
				</div>
			</div>
			<button
				type="button"
				class="btn-cancel"
				@click="newAgent.ai_skills.push({ skill: '', version_pin: '' })"
			>
				+ Add skill
			</button>
		</div>

		<div class="field-row two-col">
			<div>
				<label>PII Input Screening</label>
				<select v-model="newAgent.pii_screening">
					<option value="">Default (Enabled)</option>
					<option value="Enabled">Enabled</option>
					<option value="Disabled">Disabled</option>
				</select>
			</div>
			<div>
				<label>Output Screening</label>
				<select v-model="newAgent.output_screening_mode">
					<option value="">Default (Flag)</option>
					<option value="Log">Log — record only</option>
					<option value="Flag">Flag — redact the offending text</option>
					<option value="Block">Block — withhold the reply</option>
				</select>
			</div>
		</div>
		<span class="field-hint">
			Screening applies to what the user sends in and what the agent says back. Both can be
			changed later on the agent.
		</span>
		<div class="field-row create-agent-actions">
			<button type="button" class="btn-cancel" @click="showCreateAgent = false">
				Cancel
			</button>
			<button type="button" class="btn-save" :disabled="creatingAgent" @click="createAgent">
				{{ creatingAgent ? "Creating…" : "Create agent" }}
			</button>
		</div>
		<span class="field-hint">
			The agent is created as a Chat agent in Draft — the AI Agent Creation Process takes it
			to Live automatically and links it on this task.
		</span>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { AGENT_CONFIG_KEY } from "@/composables/AgentConfig/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const {
	availableSkills,
	showCreateAgent,
	creatingAgent,
	agentIdEdited,
	newAgent,
	filteredCatalogModels,
	modelLabel,
	scrubbedAgentId,
	createAgent,
} = ac;
</script>

<style scoped src="./AgentConfigCreatePanel.css"></style>
