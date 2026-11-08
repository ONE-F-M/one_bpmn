<template>
	<!-- ============ Memory ============ -->
	<div class="field-group-title" v-if="!isSelector">Memory</div>

	<!-- Conversation store backend -->
	<div class="field-row" v-if="!isSelector">
		<label>Conversation Store</label>
		<select v-model="form.aiConversationStore">
			<option value="process_variable">Process Variable (transient)</option>
			<option value="document_store">Document Store (persistent)</option>
			<option value="custom">Custom</option>
		</select>
		<span class="field-hint"
			>Where this agent's message thread is kept. Process Variable lives in the instance and
			is discarded with it.</span
		>
	</div>

	<!-- Context window size -->
	<div class="field-row" v-if="!isSelector">
		<label>Context Window <span class="hint">(max messages)</span></label>
		<input type="number" v-model.number="form.aiContextMaxMessages" min="1" />
		<span class="field-hint"
			>Most recent messages kept when priming a call; the system prompt is always
			retained.</span
		>
	</div>

	<!-- Long-term memory toggle -->
	<div class="field-row" style="margin-top: 8px" v-if="!isSelector">
		<label class="checkbox-row">
			<input type="checkbox" v-model="form.aiLongTermMemory" class="checkbox-input" />
			<span>Enable long-term memory</span>
		</label>
		<span class="field-hint"
			>Recall relevant saved memories before the call, and optionally save one after.</span
		>
	</div>

	<!-- Memory scope (only when long-term memory is on) -->
	<div class="field-row" v-if="!isSelector && form.aiLongTermMemory">
		<label>Memory Scope</label>
		<select v-model="form.aiMemoryScope">
			<option value="Agent">Agent (this task)</option>
			<option value="Process">Process (this process model)</option>
			<option value="Entity">Entity (the context document)</option>
		</select>
		<span class="field-hint" v-if="form.aiMemoryScope === 'Entity'">
			The entity is taken from the task's context document (context_doctype /
			context_docname) at runtime — no extra field needed.
		</span>
	</div>

	<!-- Recall token budget (only when long-term memory is on). Governs
               what gets INJECTED, independent of write mode — recall runs
               whenever memory is on, whatever the write mode is set to. -->
	<div class="field-row" v-if="!isSelector && form.aiLongTermMemory">
		<label>Memory Token Budget</label>
		<input type="number" min="0" step="100" v-model.number="form.aiMemoryTokenBudget" />
		<span class="field-hint">
			Caps the injected recall block by estimated token size, truncating the lowest-ranked
			memories first. 0 or blank uses the default (800) — there is no way to disable the cap
			here, unlike Context Token Budget below: an unbounded block is the defect this field
			exists to close.
		</span>
	</div>

	<!-- Memory write mode (only when long-term memory is on) -->
	<div class="field-row" v-if="!isSelector && form.aiLongTermMemory">
		<label>Memory Write Mode</label>
		<select v-model="form.aiMemoryWriteMode">
			<option value="off">Off (recall only)</option>
			<option value="distilled">Distilled facts (recommended)</option>
			<option value="raw">Raw output (legacy)</option>
		</select>
		<span class="field-hint">
			Distilled extracts durable, deduplicated facts worth remembering (skipping
			confirmations and one-off replies); Raw stores the full agent output verbatim.
		</span>
	</div>

	<!-- the models that do the memory writes, independent of
               the agent's chat model and of each other. Only shown for the
               distilled path — raw writes call no model at all. -->
	<div
		class="field-row"
		v-if="!isSelector && form.aiLongTermMemory && form.aiMemoryWriteMode === 'distilled'"
	>
		<label>Distillation Model <span class="hint">(optional)</span></label>
		<select v-model="form.aiMemoryDistillModel">
			<option value="">{{ inheritLabel("distill") }}</option>
			<option
				v-if="unlistedModelLabel(form.aiMemoryDistillModel)"
				:value="form.aiMemoryDistillModel"
			>
				{{ unlistedModelLabel(form.aiMemoryDistillModel) }}
			</option>
			<option v-for="m in filteredCatalogModels" :key="'distill-' + m.name" :value="m.name">
				{{ modelLabel(m) }}
			</option>
		</select>
		<span class="field-hint">
			Extracts durable facts from the run. A cheaper, faster model is usually enough. Left
			blank this falls back to the site default in Processa Settings, then to the agent's own
			model.
		</span>
	</div>

	<div
		class="field-row"
		v-if="!isSelector && form.aiLongTermMemory && form.aiMemoryWriteMode === 'distilled'"
	>
		<label>Reconciliation Model <span class="hint">(optional)</span></label>
		<select v-model="form.aiMemoryReconcileModel">
			<option value="">{{ inheritLabel("reconcile") }}</option>
			<option
				v-if="unlistedModelLabel(form.aiMemoryReconcileModel)"
				:value="form.aiMemoryReconcileModel"
			>
				{{ unlistedModelLabel(form.aiMemoryReconcileModel) }}
			</option>
			<option
				v-for="m in filteredCatalogModels"
				:key="'reconcile-' + m.name"
				:value="m.name"
			>
				{{ modelLabel(m) }}
			</option>
		</select>
		<span class="field-hint">
			Decides add / update / replace against existing memories. Raise this one when
			reconciliations are poor.
		</span>
	</div>

	<!-- Conversation compaction: replace old turns with a summary rather
               than letting them fall off the end of the window. Agent-level for
               the same reason memory is — a conversation belongs to the agent,
               not to whichever task happened to call it. -->
	<div class="field-row" v-if="!isSelector">
		<label>Context Token Budget <span class="hint">(0 = no size limit)</span></label>
		<input type="number" min="0" step="500" v-model.number="form.aiContextTokenBudget" />
		<span class="field-hint">
			Caps the history by estimated SIZE as well as by message count — both apply, whichever
			bites first. Message count is blind to size: twenty one-line turns and twenty huge tool
			results both read as twenty, and only the second kind blows the context window. Left at
			0 this falls back to the site default in Processa Settings.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector">
		<label>
			<input type="checkbox" v-model="form.aiCompactionEnabled" />
			Compact long conversations
		</label>
		<span class="field-hint">
			Summarises the early turns once and sends the summary plus the recent turns
			word-for-word, so a long conversation keeps its beginning without re-sending it every
			time. The summary is always written in the background — a turn never waits for it.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiCompactionEnabled">
		<label>Keep Recent Messages</label>
		<input type="number" min="2" v-model.number="form.aiCompactionKeepTail" />
		<span class="field-hint">
			How many of the most recent messages stay word-for-word. Everything older is what the
			summary replaces.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiCompactionEnabled">
		<label>Compaction Model <span class="hint">(optional)</span></label>
		<select v-model="form.aiCompactionModel">
			<option value="">{{ inheritLabel("compaction") }}</option>
			<option
				v-if="unlistedModelLabel(form.aiCompactionModel)"
				:value="form.aiCompactionModel"
			>
				{{ unlistedModelLabel(form.aiCompactionModel) }}
			</option>
			<option
				v-for="m in filteredCatalogModels"
				:key="'compaction-' + m.name"
				:value="m.name"
			>
				{{ modelLabel(m) }}
			</option>
		</select>
		<span class="field-hint">
			Writes the summary. This is high-volume, low-stakes work, so a cheap model belongs
			here. Left blank it falls back to the site default in Processa Settings.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiCompactionEnabled">
		<label>Token Threshold <span class="hint">(0 = off)</span></label>
		<input type="number" min="0" v-model.number="form.aiCompactionTokenThreshold" />
		<span class="field-hint">
			Compact once the history being sent is estimated to pass this many tokens.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiCompactionEnabled">
		<label>Idle Minutes <span class="hint">(0 = off)</span></label>
		<input type="number" min="0" v-model.number="form.aiCompactionIdleMinutes" />
		<span class="field-hint">
			Compact a conversation nobody has touched for this long. Checked hourly.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiCompactionEnabled">
		<label>
			<input type="checkbox" v-model="form.aiCompactionOnTaskBoundary" />
			Compact at the end of every turn
		</label>
		<span class="field-hint">
			Runs once the agent has replied, so it never happens part-way through a turn. Set any
			combination of the three — whichever fires first does the work.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector">
		<label>Tool Loop Threshold <span class="hint">(0 = off)</span></label>
		<input type="number" min="0" step="1000" v-model.number="form.aiLoopCompactionThreshold" />
		<span class="field-hint">
			Inside one run: once a model call's prompt passes this many tokens, the older tool
			turns are replaced by a summary and the list of files read and edited. Works without
			"Compact long conversations". Used by coding agents with long tool loops.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector && form.aiLoopCompactionThreshold > 0">
		<label>Tool Loop Keep Turns</label>
		<input type="number" min="3" v-model.number="form.aiLoopCompactionKeepTurns" />
		<span class="field-hint">
			How many of the latest tool turns stay word-for-word. At least 3.
		</span>
	</div>

	<div class="field-group-title" v-if="!isSelector">Golden Dataset</div>

	<div class="field-row" v-if="!isSelector">
		<label>Minimum Cases <span class="hint">(blank = no bar)</span></label>
		<input type="number" min="0" v-model.number="form.aiGoldenDatasetMinimum" />
		<span class="field-hint">
			Cases this agent needs before its golden dataset counts as representative. Left blank,
			the dataset shows its count and nothing to measure it against.
		</span>
	</div>

	<div class="field-row" v-if="!isSelector">
		<label>Target Cases <span class="hint">(optional)</span></label>
		<input type="number" min="0" v-model.number="form.aiGoldenDatasetTarget" />
		<span class="field-hint"
			>The size the dataset is aiming for, shown beside the minimum.</span
		>
	</div>

	<p class="field-hint" style="margin-top: 10px" v-if="!isSelector">
		Memory, compaction and golden dataset settings are stored on the linked AI Agent
		Configuration, not on this diagram.
	</p>
</template>

<script setup>
import { inject } from "vue";
import { AGENT_CONFIG_KEY } from "@/composables/useAgentConfigState";

const ac = inject(AGENT_CONFIG_KEY);
const { form, isSelector, filteredCatalogModels, unlistedModelLabel, modelLabel, inheritLabel } =
	ac;
</script>

<style scoped src="./AgentConfigMemory.css"></style>
