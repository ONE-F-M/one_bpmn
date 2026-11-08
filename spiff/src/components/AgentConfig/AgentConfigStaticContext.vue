<template>
	<!-- ============ Static context ============ -->
	<!-- Examples and guard rails live on the linked agent, not on this
               diagram, and they are FROZEN: identical on every loop iteration
               of every turn. Editing them here edits the agent.
               They close out Advanced Settings rather than forming groups of
               their own — they tune how one agent behaves, the same as the
               sampling params above, and Memory below is the next real
               section. -->
	<template v-if="!isSelector && form.aiAgentConfig">
		<div class="field-row">
			<label>Examples <span class="hint">(optional)</span></label>
			<span class="field-hint">
				Worked examples that <em>demonstrate</em> the behaviour — a format, or a judgement
				call that is hard to state as a rule. Rendered after the system prompt, in this
				order.
			</span>
			<div v-for="(ex, i) in form.aiExamples" :key="'ex-' + i" class="static-row">
				<div class="static-row-head">
					<label class="checkbox-row">
						<input
							type="checkbox"
							class="checkbox-input"
							:checked="ex.enabled !== 0"
							@change="ex.enabled = $event.target.checked ? 1 : 0"
						/>
						<span>Enabled</span>
					</label>
					<span class="static-row-num">Example {{ i + 1 }}</span>
					<button
						type="button"
						class="close-btn"
						title="Remove"
						@click="form.aiExamples.splice(i, 1)"
					>
						✕
					</button>
				</div>
				<div class="static-field">
					<span class="static-field-label"
						>User says <em>— the input to match on</em></span
					>
					<textarea
						v-model="ex.input"
						rows="2"
						placeholder="e.g. How many staff are on shift today?"
					/>
				</div>
				<div class="static-field">
					<span class="static-field-label"
						>Context <em>- what the agent knew when the message arrived</em></span
					>
					<textarea
						v-model="ex.context_summary"
						rows="2"
						placeholder="e.g. The Leave Request form is open."
					/>
				</div>
				<ExampleTrajectory v-if="ex.trajectory" v-model="ex.trajectory" />
				<div class="static-field">
					<span class="static-field-label"
						>Agent should answer <em>— the reply to imitate</em></span
					>
					<textarea v-model="ex.expected_output" rows="2" placeholder="e.g. 14." />
				</div>
				<div class="static-field">
					<!-- The note IS rendered ("Note: ..." under the example), so
                       don't describe it as an internal comment. -->
					<span class="static-field-label"
						>Note <em>— an aside for the agent about this example</em></span
					>
					<input
						type="text"
						v-model="ex.note"
						placeholder="e.g. Answer the number alone, no preamble."
					/>
				</div>
			</div>
			<button type="button" class="btn-cancel" @click="addExample">+ Add example</button>
		</div>

		<div class="field-row">
			<label>Guard Rails <span class="hint">(optional)</span></label>
			<span class="field-hint">
				Rules the agent must obey on every turn, each stated imperatively. Rendered last in
				the static context, grouped by category.
			</span>
			<div v-for="(g, i) in form.aiGuardrails" :key="'gr-' + i" class="static-row">
				<div class="static-row-head">
					<label class="checkbox-row">
						<input
							type="checkbox"
							class="checkbox-input"
							:checked="g.enabled !== 0"
							@change="g.enabled = $event.target.checked ? 1 : 0"
						/>
						<span>Enabled</span>
					</label>
					<span class="static-row-inline-label">Category</span>
					<select v-model="g.category" class="static-row-cat">
						<option v-for="c in GUARDRAIL_CATEGORIES" :key="c" :value="c">
							{{ c }}
						</option>
					</select>
					<span class="static-row-num">Rule {{ i + 1 }}</span>
					<button
						type="button"
						class="close-btn"
						title="Remove"
						@click="form.aiGuardrails.splice(i, 1)"
					>
						✕
					</button>
				</div>
				<div class="static-field">
					<span class="static-field-label"
						>The rule <em>— phrase it as an instruction</em></span
					>
					<textarea
						v-model="g.guardrail"
						rows="2"
						placeholder="e.g. Never emit a file longer than 300 lines — split it instead."
					/>
				</div>
			</div>
			<button type="button" class="btn-cancel" @click="addGuardrail">
				+ Add guard rail
			</button>
		</div>

		<p class="field-hint" style="margin-top: 10px">
			Examples and guard rails are stored on the linked AI Agent Configuration, not on this
			diagram, and apply to every task that links it.
		</p>
		<div class="field-row">
			<label>Skills <span class="hint">(optional)</span></label>
			<span class="field-hint"> Skills enabled for this agent. </span>
			<div v-for="(s, i) in form.aiSkills" :key="'sk-' + i" class="static-row">
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
						@click="form.aiSkills.splice(i, 1)"
					>
						✕
					</button>
				</div>
			</div>
			<button type="button" class="btn-cancel" @click="addSkill">+ Add skill</button>
		</div>

		<!-- What the agent is PERMITTED to do. An agent acts as its own user
                 and is allowed or refused by the roles that user holds, so this
                 list is the whole answer to "may this agent do that" — add one to
                 grant, remove one to revoke, nothing to deploy either way. -->
		<div class="field-row">
			<label>Permissions <span class="hint">(roles the agent holds)</span></label>
			<span class="field-hint">
				The agent acts as its own user, <strong>{{ agentUserLabel }}</strong
				>, and every write it makes is allowed or refused by these roles. An empty list
				means it can read and change nothing. Removing a role revokes it immediately — the
				next thing the agent tries is refused, and it is told why.
			</span>
			<div v-for="(r, i) in form.aiAgentRoles" :key="'role-' + i" class="static-row">
				<div class="static-row-head">
					<span class="static-row-inline-label">Role</span>
					<select v-model="r.role" class="static-row-cat">
						<option value="">Pick a role…</option>
						<option v-for="name in roleOptions" :key="name" :value="name">
							{{ name }}
						</option>
					</select>
					<button
						type="button"
						class="close-btn"
						title="Revoke"
						@click="form.aiAgentRoles.splice(i, 1)"
					>
						✕
					</button>
				</div>
			</div>
			<button type="button" class="btn-cancel" @click="addAgentRole">+ Grant a role</button>
			<span v-if="!rolesUnrestricted" class="field-hint">
				You can grant only roles you hold yourself — an agent acts with what it is given,
				so granting one you do not have would be a way around your own permissions.
			</span>
		</div>
	</template>
</template>

<script setup>
import { inject } from "vue";
import ExampleTrajectory from "@/components/AgentConfig/ExampleTrajectory.vue";
import { AGENT_CONFIG_KEY } from "@/composables/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const {
	availableSkills,
	rolesUnrestricted,
	form,
	isSelector,
	addSkill,
	addAgentRole,
	agentUserLabel,
	roleOptions,
	addExample,
	addGuardrail,
} = ac;

// Mirrors the AI Agent Guard Rail Select options; the backend rejects anything
// else back to "Other".
const GUARDRAIL_CATEGORIES = [
	"Code Quality",
	"Performance",
	"Cost & Tokens",
	"Safety",
	"Output Format",
	"Other",
];
</script>

<style scoped src="@/components/AgentConfig/agentConfigModal.css"></style>
