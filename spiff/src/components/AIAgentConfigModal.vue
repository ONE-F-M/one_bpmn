<template>
  <div class="ai-agent-modal-overlay" @click.self="$emit('close')">
    <div class="ai-agent-modal">
      <!-- ============ LEFT: configuration form ============ -->
      <div class="modal-main">
        <div class="modal-header">
          <h3>{{ isSelector ? "Configure AI Task Selector" : "Configure AI Agent Task" }}</h3>
          <button class="close-btn" @click="$emit('close')">✕</button>
        </div>

        <div class="modal-body">
          <!-- Linked AI Agent Configuration (WI-001637 live link). Selecting
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
              <option v-for="c in agentConfigs" :key="c.name" :value="c.name">
                {{ c.name }}
              </option>
              <option value="__create__">＋ Create new…</option>
            </select>
            <span v-if="form.aiAgentConfig && form.aiAgentConfig !== '__create__'" class="field-hint">
              <span :class="['agent-status', agentStatusClass]" :title="'Deployment requires Live (WI-001652)'">
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
              >{{ rerunning ? "Re-running…" : "Re-run checks" }}</button>
              Prompt, provider, model and params resolve from this configuration
              when the process runs. Saving writes your edits back to it.
              Deploying this diagram requires the agent to be Live.
            </span>
          </div>

          <!-- WI-001648: create a new AI Agent Configuration without leaving
               Processa. Inserted as Chat + Draft, so the AI Agent Creation
               Process takes it validate → provision → evaluate → Live on its
               own; the new agent is auto-linked on this shape. -->
          <div v-if="showCreateAgent" class="create-agent-panel">
            <div class="field-group-title">New AI Agent Configuration</div>
            <div class="field-row two-col">
              <div>
                <label>Agent Name <span class="hint">(required)</span></label>
                <input type="text" v-model="newAgent.agent_name" placeholder="e.g. Leave Summarizer" />
              </div>
              <div>
                <label>Agent ID</label>
                <input type="text" v-model="newAgent.agent_id" :placeholder="scrubbedAgentId || 'auto from name'" @input="agentIdEdited = true" />
              </div>
            </div>
            <div class="field-row two-col">
              <div>
                <label>Chat Mode Label <span class="hint">(required, unique)</span></label>
                <input type="text" v-model="newAgent.chat_mode_label" placeholder="e.g. Leave Summarizer" />
              </div>
              <div>
                <label>AI Model <span class="hint">(provider follows the model)</span></label>
                <select v-model="newAgent.ai_model">
                  <option value="">-- Pick a Model --</option>
                  <option v-for="m in catalogModels" :key="m.name" :value="m.name">
                    {{ m.name }} — via {{ m.ai_provider_credentials }}
                  </option>
                </select>
              </div>
            </div>
            <div class="field-row">
              <label>System Prompt <span class="hint">(leave empty to auto-generate from the description)</span></label>
              <textarea v-model="newAgent.system_prompt" rows="3" />
            </div>
            <div class="field-row">
              <label>Description</label>
              <textarea v-model="newAgent.description" rows="2" placeholder="What this agent does — feeds prompt auto-generation" />
            </div>
            <div class="field-row">
              <label>Sample Prompts <span class="hint">(optional — become the baseline eval suite)</span></label>
              <div v-for="(sp, i) in newAgent.sample_prompts" :key="i" class="sample-prompt-row">
                <input type="text" v-model="sp.prompt" placeholder="Sample user prompt" />
                <input type="text" v-model="sp.expected_behaviour" placeholder="Expected behaviour (optional)" />
                <button type="button" class="close-btn" title="Remove" @click="newAgent.sample_prompts.splice(i, 1)">✕</button>
              </div>
              <button type="button" class="btn-cancel" @click="newAgent.sample_prompts.push({ prompt: '', expected_behaviour: '' })">
                + Add sample prompt
              </button>
            </div>
            <div class="field-row">
              <label>Skills <span class="hint">(optional)</span></label>
              <div v-for="(s, i) in newAgent.ai_skills" :key="'newsk-' + i" class="static-row">
                <div class="static-row-head">
                  <span class="static-row-inline-label">Skill</span>
                  <select v-model="s.skill" class="static-row-cat">
                    <option v-for="c in availableSkills" :key="c.name" :value="c.name">{{ c.name }}</option>
                  </select>
                  <span class="static-row-inline-label">Version pin</span>
                  <input v-model="s.version_pin" type="text" placeholder="e.g. 1.0.0 (optional)" class="static-row-cat" />
                  <button type="button" class="close-btn" title="Remove" @click="newAgent.ai_skills.splice(i, 1)">✕</button>
                </div>
              </div>
              <button type="button" class="btn-cancel" @click="newAgent.ai_skills.push({ skill: '', version_pin: '' })">
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
              Screening applies to what the user sends in and what the agent says back.
              Both can be changed later on the agent.
            </span>
            <div class="field-row create-agent-actions">
              <button type="button" class="btn-cancel" @click="showCreateAgent = false">Cancel</button>
              <button type="button" class="btn-save" :disabled="creatingAgent" @click="createAgent">
                {{ creatingAgent ? "Creating…" : "Create agent" }}
              </button>
            </div>
            <span class="field-hint">
              The agent is created as a Chat agent in Draft — the AI Agent Creation
              Process takes it to Live automatically and links it on this task.
            </span>
          </div>

          <!-- Backend (selector always runs direct_api) -->
          <div class="field-row" v-if="!isSelector">
            <label>Backend</label>
            <select v-model="form.aiBackend">
              <option value="direct_api">Direct API</option>
              <option value="antigravity">Google Antigravity SDK</option>
            </select>
          </div>

          <!-- AI Provider — read-only since WI-001650: the provider is an
               agent property, resolved from the linked configuration. -->
          <div class="field-row">
            <label>AI Provider <span class="hint">(from the linked configuration)</span></label>
            <select v-model="form.aiProvider" disabled>
              <option value="">-- Link an agent configuration --</option>
              <option v-for="p in providers" :key="p.name" :value="p.name">
                {{ p.provider_name }}
              </option>
            </select>
          </div>

          <!-- Model — the agent's catalog pick (WI-001655): editable here and
               written back to the linked configuration on Save; the provider
               follows the model automatically. -->
          <div class="field-row">
            <label>Model <span class="hint">(the agent's catalog pick — saving writes it back; provider follows)</span></label>
            <select v-model="form.aiModel">
              <option value="">-- Pick a Model --</option>
              <option v-if="form.aiModel && !catalogModels.some(m => m.name === form.aiModel)" :value="form.aiModel">
                {{ form.aiModel }} (not in catalog)
              </option>
              <option v-for="m in catalogModels" :key="m.name" :value="m.name">
                {{ m.name }} — via {{ m.ai_provider_credentials }}
              </option>
            </select>
          </div>

          <!-- Output variable (selector output is the chosen task, not a variable) -->
          <div class="field-row" v-if="!isSelector">
            <label>Output Variable Name</label>
            <input type="text" v-model="form.aiOutputVariable" placeholder="ai_result" />
          </div>

          <!-- System prompt -->
          <div class="field-row">
            <label>System Prompt <span class="hint">(Jinja: {{ '{{' }} doc }}, {{ '{{' }} instance }})</span></label>
            <textarea v-model="form.aiSystemPrompt" rows="4" />
          </div>

          <!-- User prompt -->
          <div class="field-row">
            <label>User Prompt <span class="hint">(Jinja supported)</span></label>
            <textarea v-model="form.aiUserPrompt" rows="4" />
          </div>

          <!-- Response format (selector responses are tool calls, not text/JSON) -->
          <div class="field-row" v-if="!isSelector">
            <label>Response Format</label>
            <select v-model="form.aiResponseFormat">
              <option value="text">Text</option>
              <option value="json">JSON</option>
            </select>
          </div>

          <!-- Response schema (only when JSON) -->
          <div class="field-row" v-if="!isSelector && form.aiResponseFormat === 'json'">
            <label>Response Schema <span class="hint">(JSON Schema)</span></label>
            <textarea v-model="form.aiResponseSchema" rows="4" placeholder='{"type":"object",...}' />
          </div>

          <div class="field-group-title">Advanced Settings</div>

          <!-- Temperature (selector dispatch doesn't read sampling params) -->
          <div class="field-row two-col" v-if="!isSelector">
            <div>
              <label>Temperature</label>
              <input type="number" v-model.number="form.aiTemperature" min="0" max="2" step="0.1" />
            </div>
            <div>
              <label>Top P</label>
              <input type="number" v-model.number="form.aiTopP" min="0" max="1" step="0.05" />
            </div>
          </div>

          <div class="field-row two-col">
            <div>
              <label>Max Tokens</label>
              <input type="number" v-model.number="form.aiMaxTokens" min="1" />
            </div>
            <div>
              <label>Timeout (seconds)</label>
              <input type="number" v-model.number="form.aiTimeout" min="1" />
            </div>
          </div>

          <div class="field-row" v-if="!isSelector">
            <label>Max Retries</label>
            <input type="number" v-model.number="form.aiMaxRetries" min="0" max="10" />
          </div>

          <div class="field-row" style="margin-top: 8px;" v-if="!isSelector">
            <label class="checkbox-row">
              <input type="checkbox" v-model="form.aiStopOnError" class="checkbox-input" />
              <span>Stop process on error</span>
            </label>
            <span class="field-hint">If checked, the process instance will halt when this AI task fails.</span>
          </div>

          <!-- ============ Static context (WI-001639) ============ -->
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
                Worked examples that <em>demonstrate</em> the behaviour — a format, or a
                judgement call that is hard to state as a rule. Rendered after the system
                prompt, in this order.
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
                  <button type="button" class="close-btn" title="Remove" @click="form.aiExamples.splice(i, 1)">✕</button>
                </div>
                <div class="static-field">
                  <span class="static-field-label">User says <em>— the input to match on</em></span>
                  <textarea v-model="ex.input" rows="2" placeholder="e.g. How many staff are on shift today?" />
                </div>
                <div class="static-field">
                  <span class="static-field-label">Agent should answer <em>— the reply to imitate</em></span>
                  <textarea v-model="ex.expected_output" rows="2" placeholder="e.g. 14." />
                </div>
                <div class="static-field">
                  <!-- The note IS rendered ("Note: ..." under the example), so
                       don't describe it as an internal comment. -->
                  <span class="static-field-label">Note <em>— an aside for the agent about this example</em></span>
                  <input type="text" v-model="ex.note" placeholder="e.g. Answer the number alone, no preamble." />
                </div>
              </div>
              <button type="button" class="btn-cancel" @click="addExample">+ Add example</button>
            </div>

            <div class="field-row">
              <label>Guard Rails <span class="hint">(optional)</span></label>
              <span class="field-hint">
                Rules the agent must obey on every turn, each stated imperatively.
                Rendered last in the static context, grouped by category.
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
                    <option v-for="c in GUARDRAIL_CATEGORIES" :key="c" :value="c">{{ c }}</option>
                  </select>
                  <span class="static-row-num">Rule {{ i + 1 }}</span>
                  <button type="button" class="close-btn" title="Remove" @click="form.aiGuardrails.splice(i, 1)">✕</button>
                </div>
                <div class="static-field">
                  <span class="static-field-label">The rule <em>— phrase it as an instruction</em></span>
                  <textarea v-model="g.guardrail" rows="2" placeholder="e.g. Never emit a file longer than 300 lines — split it instead." />
                </div>
              </div>
              <button type="button" class="btn-cancel" @click="addGuardrail">+ Add guard rail</button>
            </div>

            <p class="field-hint" style="margin-top: 10px;">
              Examples and guard rails are stored on the linked AI Agent Configuration, not on
              this diagram, and apply to every task that links it.
            </p>
            <div class="field-row">
              <label>Skills <span class="hint">(optional)</span></label>
              <span class="field-hint">
                Skills enabled for this agent.
              </span>
              <div v-for="(s, i) in form.aiSkills" :key="'sk-' + i" class="static-row">
                <div class="static-row-head">
                  <span class="static-row-inline-label">Skill</span>
                  <select v-model="s.skill" class="static-row-cat">
                    <option v-for="c in availableSkills" :key="c.name" :value="c.name">{{ c.name }}</option>
                  </select>
                  <span class="static-row-inline-label">Version pin</span>
                  <input v-model="s.version_pin" type="text" placeholder="e.g. 1.0.0 (optional)" class="static-row-cat" />
                  <button type="button" class="close-btn" title="Remove" @click="form.aiSkills.splice(i, 1)">✕</button>
                </div>
              </div>
              <button type="button" class="btn-cancel" @click="addSkill">+ Add skill</button>
            </div>

          </template>

          <!-- ============ Screening ============ -->
          <!-- Agent-level, like Memory below: what an agent may say is a property
               of the agent, not of the task that happens to call it.

               Rendered from the agent's OWN fields rather than a hard-coded list.
               15.1 has since added the output mode and it now appears here by
               itself, which is what this was built for; the injection mode
               (WI-001840) will do the same. Labels, options and the explanatory
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
                <input v-else-if="c.fieldtype === 'Check'" type="checkbox" class="checkbox-input"
                       :checked="c.value == 1" @change="c.value = $event.target.checked ? 1 : 0" />
                <input v-else-if="c.fieldtype === 'Int'" type="number" min="0" v-model.number="c.value" />
                <input v-else type="text" v-model="c.value" />
                <span class="field-hint" v-if="c.description">{{ c.description }}</span>
              </div>
            </template>
            <p class="field-hint" style="margin-top: 6px;">
              These are stored on the linked AI Agent Configuration and apply wherever
              this agent runs.
            </p>
          </template>

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
            <span class="field-hint">Where this agent's message thread is kept. Process Variable lives in the instance and is discarded with it.</span>
          </div>

          <!-- Context window size -->
          <div class="field-row" v-if="!isSelector">
            <label>Context Window <span class="hint">(max messages)</span></label>
            <input type="number" v-model.number="form.aiContextMaxMessages" min="1" />
            <span class="field-hint">Most recent messages kept when priming a call; the system prompt is always retained.</span>
          </div>

          <!-- Long-term memory toggle -->
          <div class="field-row" style="margin-top: 8px;" v-if="!isSelector">
            <label class="checkbox-row">
              <input type="checkbox" v-model="form.aiLongTermMemory" class="checkbox-input" />
              <span>Enable long-term memory</span>
            </label>
            <span class="field-hint">Recall relevant saved memories before the call, and optionally save one after.</span>
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
              The entity is taken from the task's context document (context_doctype / context_docname) at runtime — no extra field needed.
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
              Distilled extracts durable, deduplicated facts worth remembering (skipping confirmations and one-off replies);
              Raw stores the full agent output verbatim.
            </span>
          </div>

          <!-- WI-001793: the models that do the memory writes, independent of
               the agent's chat model and of each other. Only shown for the
               distilled path — raw writes call no model at all. -->
          <div
            class="field-row"
            v-if="!isSelector && form.aiLongTermMemory && form.aiMemoryWriteMode === 'distilled'"
          >
            <label>Distillation Model <span class="hint">(optional)</span></label>
            <select v-model="form.aiMemoryDistillModel">
              <option value="">-- Use the default --</option>
              <option
                v-if="form.aiMemoryDistillModel && !catalogModels.some(m => m.name === form.aiMemoryDistillModel)"
                :value="form.aiMemoryDistillModel"
              >
                {{ form.aiMemoryDistillModel }} (not in catalog)
              </option>
              <option v-for="m in catalogModels" :key="'distill-' + m.name" :value="m.name">
                {{ m.name }} — via {{ m.ai_provider_credentials }}
              </option>
            </select>
            <span class="field-hint">
              Extracts durable facts from the run. A cheaper, faster model is usually enough.
              Left blank this falls back to the site default in Processa Settings, then to the agent's own model.
            </span>
          </div>

          <div
            class="field-row"
            v-if="!isSelector && form.aiLongTermMemory && form.aiMemoryWriteMode === 'distilled'"
          >
            <label>Reconciliation Model <span class="hint">(optional)</span></label>
            <select v-model="form.aiMemoryReconcileModel">
              <option value="">-- Use the default --</option>
              <option
                v-if="form.aiMemoryReconcileModel && !catalogModels.some(m => m.name === form.aiMemoryReconcileModel)"
                :value="form.aiMemoryReconcileModel"
              >
                {{ form.aiMemoryReconcileModel }} (not in catalog)
              </option>
              <option v-for="m in catalogModels" :key="'reconcile-' + m.name" :value="m.name">
                {{ m.name }} — via {{ m.ai_provider_credentials }}
              </option>
            </select>
            <span class="field-hint">
              Decides add / update / replace against existing memories. Raise this one when reconciliations are poor.
            </span>
          </div>

          <p class="field-hint" style="margin-top: 10px;" v-if="!isSelector">
            Memory settings are stored on the linked AI Agent Configuration, not on this diagram.
          </p>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="$emit('close')">Cancel</button>
          <button class="btn-save" @click="save">Save</button>
        </div>
      </div>

      <!-- ============ RIGHT: assistant chat panel ============ -->
      <div class="assistant-panel">
        <!-- WI-001679: ONE chat for both ways into this dialog. An AI Agent
             Task and an AI Task Selector now open the same panel, on the same
             agent, over the same endpoint — the mode only changes what the
             turn is grounded with (server-side) and which fields the reply may
             recommend. The panel's own titlebar (avatar + name + config-driven
             badge) is the header in both; the legacy purple header, the manual
             Context DocType / Sample Record controls and the selector-only
             transcript are gone. The assistant is always available: with no
             linked configuration yet it runs on its own credentials
             (WI-001623), so you can ask it to create the agent this task will
             link. -->
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
import { ref, computed, onMounted, onUnmounted, toRaw } from "vue";
import { Dialog, frappeRequest } from "frappe-ui";
import { frappeGet } from "@/bpmn/shared/frappeResource";
// WI-001674: agent mode chats through the shared panel + card registry.
import { AgentChatPanel } from "@/components/chat";
import { cardRegistry } from "@/components/chat/cards/registry";
const availableSkills = ref([]);
function addSkill() { form.value.aiSkills.push({ skill: '', version_pin: '' }); }


// bpmn-js elements must never be touched as Vue reactive proxies — the renderer
// reads non-configurable properties (e.g. labels) that a Proxy cannot return,
// throwing on re-render. Always unwrap to the raw element before using it.
function rawElement() {
  return toRaw(props.element);
}

const props = defineProps({
  element: { type: Object, required: true },
  modeler: { type: Object, required: true },
  // "agent" (AI Agent Task) or "selector" (AI Task Selector on an ad-hoc
  // subprocess). Selector mode hides fields the selector dispatch never
  // reads (backend, output variable, response format/schema, sampling,
  // retries) and writes only the selector attribute set on save.
  mode: { type: String, default: "agent" },
});

const isSelector = computed(() => props.mode === "selector");

const emit = defineEmits(["close"]);

const providers = ref([]);
const agentConfigs = ref([]);
const catalogModels = ref([]); // AI Model catalog (WI-001655)


// ── Create-new-agent panel state (WI-001648) ──
const showCreateAgent = ref(false);
const creatingAgent = ref(false);
const agentIdEdited = ref(false);
const emptyNewAgent = () => ({
  agent_name: "",
  agent_id: "",
  chat_mode_label: "",
  ai_model: "",
  system_prompt: "",
  description: "",
  sample_prompts: [],
  ai_skills: [],
  // WI-001644: chosen at creation rather than left to a later visit to the desk
  // form. Blank means "take the doctype default", so the panel never has to
  // restate what that default is.
  pii_screening: "",
  output_screening_mode: "",
});
const newAgent = ref(emptyNewAgent());
const scrubbedAgentId = computed(() =>
  (newAgent.value.agent_name || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
);

// ── Linked agent lifecycle badge (WI-001652): deployment requires Live ──
const linkedAgentStatus = ref("");
const agentStatusClass = computed(() =>
  linkedAgentStatus.value === "Live"
    ? "agent-status-live"
    : ["Needs Attention", "Retired"].includes(linkedAgentStatus.value)
      ? "agent-status-bad"
      : "agent-status-pending"
);
async function refreshLinkedAgentStatus() {
  linkedAgentStatus.value = "";
  const name = form.value.aiAgentConfig;
  if (!name || name === "__create__") return;
  try {
    const r = await frappeRequest({
      url: "/api/method/frappe.client.get_value",
      params: {
        doctype: "AI Agent Configuration",
        filters: name,
        fieldname: "lifecycle_status",
      },
    });
    linkedAgentStatus.value = (r && r.lifecycle_status) || "";
  } catch (e) {
    /* badge stays blank */
  }
}

const rerunning = ref(false);

// ── Per-agent screening (WI-001970) ─────────────────────────────────────────
// The list comes from the server, which reads the doctype's real fields, so this
// component never has to know which screening stories have shipped.
const screeningControls = ref([]);

// A control is hidden when the control it depends on is off. The server sends a
// plain fieldname rather than the doctype's "eval:" expression, so nothing here
// has to evaluate anything — and a dependency we could not reduce arrives as
// null and the control simply renders, which is the safe direction.
function isOn(fieldname) {
  const dep = screeningControls.value.find((c) => c.fieldname === fieldname);
  if (!dep) return true;
  return !(dep.value === 0 || dep.value === "0" || dep.value === false || dep.value == null);
}
function visibleIn(group) {
  return group.controls.filter((c) => !c.depends_on_field || isOn(c.depends_on_field));
}

// Rendered group by group, in the order the server sent them. Grouping comes
// from the server rather than a list here, for the same reason the controls
// themselves do: a second copy in the Vue is one more thing to fall out of step.
const controlGroups = computed(() => {
  const out = [];
  for (const c of screeningControls.value) {
    const name = c.group || "Screening";
    let g = out.find((x) => x.name === name);
    if (!g) out.push((g = { name, controls: [] }));
    g.controls.push(c);
  }
  return out;
});

async function loadScreening() {
  screeningControls.value = [];
  const name = form.value.aiAgentConfig;
  if (!name || name === "__create__") return;
  try {
    const r = await frappeRequest({
      url: "/api/method/one_bpmn.api.security_api.agent_screening",
      method: "POST",
      params: { agent: name },
    });
    screeningControls.value = (r && r.controls) || [];
  } catch (e) {
    /* an unreadable agent simply shows no screening section */
  }
}

async function saveScreening() {
  const name = form.value.aiAgentConfig;
  if (!name || !screeningControls.value.length) return;
  const values = {};
  screeningControls.value.forEach((c) => { values[c.fieldname] = c.value; });
  try {
    await frappeRequest({
      url: "/api/method/one_bpmn.api.security_api.save_agent_screening",
      method: "POST",
      params: { agent: name, values: JSON.stringify(values) },
    });
  } catch (e) {
    showNotice("Screening settings not saved", serverMessage(e));
  }
}

// Hand the agent back to the Agent Creation Process. Decides nothing itself —
// whether it may go Live stays the map's call; this only asks it to look again,
// which is what re-runs the adversarial suite and the other validations.
async function rerunChecks() {
  const name = form.value.aiAgentConfig;
  if (!name || rerunning.value) return;
  rerunning.value = true;
  try {
    await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_provisioning.rerun_creation_process",
      method: "POST",
      params: { agent: name },
    });
    // The process runs in the background, so the badge will not be right yet.
    // Poll a few times rather than leave a stale status on screen — and say so,
    // because a checks run makes real model calls and takes a minute or two.
    showNotice(
      "Re-running the agent's checks",
      "The Agent Creation Process is validating the configuration and running the " +
        "agent's adversarial suite. This makes real model calls, so give it a minute — " +
        "the status beside the agent updates on its own."
    );
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 4000));
      const before = linkedAgentStatus.value;
      await refreshLinkedAgentStatus();
      if (linkedAgentStatus.value === "Live") break;
      if (before !== linkedAgentStatus.value && linkedAgentStatus.value === "Needs Attention") break;
    }
  } catch (e) {
    showNotice("Couldn't re-run the checks", serverMessage(e));
  } finally {
    rerunning.value = false;
    refreshLinkedAgentStatus();
  }
}

// Form state — defaults
const form = ref({
  aiSkills: [],
  aiAgentConfig: "",
  aiBackend: "direct_api",
  aiProvider: "",
  aiModel: "",
  aiOutputVariable: "ai_result",
  aiSystemPrompt: "",
  aiUserPrompt: "",
  aiResponseFormat: "text",
  aiResponseSchema: "",
  aiTemperature: 0.7,
  aiTopP: 1.0,
  aiMaxTokens: 1024,
  aiTimeout: 30,
  aiMaxRetries: 2,
  aiStopOnError: false,
  // Memory
  aiConversationStore: "process_variable",
  aiContextMaxMessages: 20,
  aiLongTermMemory: false,
  aiMemoryScope: "Agent",
  aiMemoryWriteMode: "off",
  // WI-001793: blank means "inherit" — site default, then the agent's own model.
  aiMemoryDistillModel: "",
  aiMemoryReconcileModel: "",
  // WI-001639: the agent's frozen static context. Always arrays — they are
  // replaced wholesale by loadStaticContextFromConfig once the agent is read.
  aiExamples: [],
  aiGuardrails: [],
});

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

// True once the linked agent's examples/guard rails have actually been read.
// Save only writes the two tables back when this is set: an unread agent leaves
// the form arrays empty, and sending those would silently wipe its static
// context.
const staticContextLoaded = ref(false);

function addExample() {
  form.value.aiExamples.push({ input: "", expected_output: "", note: "", enabled: 1 });
}

function addGuardrail() {
  form.value.aiGuardrails.push({ guardrail: "", category: "Other", enabled: 1 });
}

// Overlay the linked agent's static-context tables onto the form. Called on
// open and whenever the linked agent changes, so what is on screen is what the
// agent will actually be primed with.
async function loadStaticContextFromConfig() {
  staticContextLoaded.value = false;
  if (!form.value.aiAgentConfig) return;
  try {
    const fields = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
      method: "POST",
      params: { config_name: form.value.aiAgentConfig },
    });
    form.value.aiExamples = Array.isArray(fields?.aiExamples) ? fields.aiExamples : [];
    
    form.value.aiSkills = Array.isArray(fields?.aiSkills) ? fields.aiSkills : [];
form.value.aiGuardrails = Array.isArray(fields?.aiGuardrails) ? fields.aiGuardrails : [];
    staticContextLoaded.value = true;
  } catch (e) {
    // Unreadable agent — the sections stay empty and Save leaves them alone.
  }
}

// ── Notices ───────────────────────────────────────────────────────────────
// Standard frappe-ui dialog for errors and confirmations — never a bare
// browser alert().
const notice = ref({ show: false, title: "", message: "" });
function showNotice(title, message) {
  notice.value = { show: true, title, message };
}

// frappe-ui's request error falls back to "<url> <ExceptionClass>" when it
// finds no friendlier text — prefer the server's own messages when present.
function serverMessage(e) {
  const msgs = Array.isArray(e?.messages) ? e.messages.filter(Boolean) : [];
  return msgs.join("\n") || e?.message || String(e);
}

// ── Assistant state ───────────────────────────────────────────────────────
const assistantConversation = ref(""); // Chat Conversation driving the dialog (WI-001623)
const chatPanel = ref(null);

// WI-001674: the modal sends RAW grounding refs; the server-side context
// builder (ai_assistant.build_assistant_turn_context) assembles the map's
// dialog_context from them — schema/sample reads stay permission-checked
// server-side, exactly as the legacy path did. WI-001679 added `mode`: the
// builder branches on it to ground a selector turn with the selector's runtime
// rules and the sub-process digest instead of the agent-creation capability.
const assistantTurnContext = computed(() => ({
  assistant_dialog: {
    mode: props.mode === "selector" ? "selector" : "agent",
    linked_config: form.value.aiAgentConfig || "",
    // The EXACT open BPMN Process Model record name — the assistant needs it
    // verbatim for proposed_config.process_model (the human-facing process
    // title is a different string and fails the WI-001997 creation gate).
    process_model: window.__ONE_BPMN_CURRENT_MODEL__ || "",
    current_config: JSON.stringify(
      props.mode === "selector"
        ? {
            aiModel: form.value.aiModel,
            aiSystemPrompt: form.value.aiSystemPrompt,
            aiUserPrompt: form.value.aiUserPrompt,
          }
        : {
            aiModel: form.value.aiModel,
            aiSystemPrompt: form.value.aiSystemPrompt,
            aiUserPrompt: form.value.aiUserPrompt,
            aiOutputVariable: form.value.aiOutputVariable,
            aiResponseFormat: form.value.aiResponseFormat,
          }
    ),
  },
}));

// Selector turns need the LIVE canvas, not the saved model: the designer is
// usually mid-edit, and the digest names the very task ids the recommended
// prompts must reference. Serializing XML is async, so it rides the panel's
// per-turn contextProvider hook (the seam ProsAlly opened in WI-001675) rather
// than the computed above, and merges over it.
async function selectorTurnContext() {
  const dialog = {
    ...assistantTurnContext.value.assistant_dialog,
    element_id: rawElement().businessObject?.id || rawElement().id || "",
    context_doctype: triggerDoctype.value || "",
  };
  try {
    const { xml } = await toRaw(props.modeler).saveXML({ format: false });
    dialog.bpmn_xml = xml;
  } catch (e) {
    // No digest this turn — the assistant works blind rather than not at all,
    // exactly as it did when the legacy path failed to serialize.
    console.warn("[AI assistant] could not serialize diagram:", e);
  }
  return { assistant_dialog: dialog };
}

// WI-001674: cards render and request — the HOST applies. The panel re-emits
// card actions here; each maps onto the SAME handlers/endpoints the legacy
// cards used, so permission checks and the creation process are identical.
async function onAssistantCardAction({ name, action, value, payload, fail }) {
  if (action === "dismiss") return;
  if (action === "confirm-create" && name === "onefm.proposed_config") {
    await createProposedAgent(fail);
    return;
  }
  if (action === "apply-fields" && name === "onefm.proposed_update") {
    // The Form-surface tray sends per-field subsets in the PAYLOAD
    // (partial applies); the full-card Apply carries no payload and falls
    // back to the event's complete field set as before.
    const fields = (payload && payload.fields) || value.fields || {};
    // A proposed update to an EXISTING config goes through the WI-001637
    // write-back; plain recommendations apply onto the open form.
    if (fields.config_name) {
      await applyProposedUpdate({ update: fields, updateState: null }, fail);
    } else {
      for (const [key, val] of Object.entries(fields)) {
        applyRecommendation(key, val);
      }
    }
  }
}

// Close the assistant's Chat Conversation on the backend so its BPMN
// orchestration runs the close branch (Cleanup → Conversation Ended) and the
// instance completes instead of staying parked at the event-based gateway.
// Fire-and-forget — same pattern as LogixChat's endConversation().
function endAssistantConversation() {
  const convName = assistantConversation.value;
  if (!convName) return;
  assistantConversation.value = "";
  frappeRequest({
    url: "/api/method/one_bpmn.api.server_script_api.end_chat_conversation",
    params: { conversation_name: convName },
  }).catch(() => {});
}

// The modal is v-if mounted per open (BpmnEditor), so unmount fires on every
// close path: ✕, Cancel, overlay click, apply-then-close, and parent teardown.
onUnmounted(endAssistantConversation);
// Grounding the designer never types: the DocType the process is triggered on.
// The manual Context DocType / Sample Record inputs retired with the legacy
// transcript (WI-001679) — the assistant looks schemas up with its own tools —
// but a selector turn still ships this one automatically, because its evidence
// template is written in {{ doc.<field> }} terms and guessing them is exactly
// what the digest cannot do for it.
const triggerDoctype = ref("");

const NUMERIC_FIELDS = ["aiTemperature", "aiTopP", "aiMaxTokens", "aiTimeout", "aiMaxRetries"];

const providerLabel = computed(() => {
  const p = providers.value.find((x) => x.name === form.value.aiProvider);
  return p ? p.provider_name : form.value.aiProvider;
});

// (WI-001655) onProviderChange lived here: picking a provider copied its
// Default Model into the Model field. Removed rather than rewritten — the
// direction it encoded is now backwards. The MODEL is the agent's pick and the
// provider is derived from that model's credentials link, so a provider can no
// longer choose a model for you. AI Provider Credentials.default_model was
// deleted with the same change, the provider select is disabled, and nothing
// called this function; it read a field that no longer exists.

// Apply one recommended value onto the open form. The card (or the tray's
// per-field Apply) is the only caller now — the legacy transcript tracked
// which suggestions had been applied itself; the shared cards own that state.
function applyRecommendation(key, value) {
  if (NUMERIC_FIELDS.includes(key)) {
    const n = Number(value);
    if (Number.isFinite(n)) form.value[key] = n;
  } else {
    form.value[key] = String(value);
  }
}

// ── Load providers + existing element config ────────────────────────────────
onMounted(async () => {
  try {
    const skills = await frappeGet("/api/resource/AI Skill", { 
      fields: JSON.stringify(["name"]),
      filters: JSON.stringify([["status", "in", ["Active", "Published"]]]), 
      limit_page_length: 100 
    });
    availableSkills.value = skills || [];
  } catch (e) {
    console.error("Failed to load skills", e);
  }

  try {
    const data = await frappeGet("/api/resource/AI Provider Credentials", {
      fields: JSON.stringify(["name", "provider_name"]),
      filters: JSON.stringify([["enabled", "=", 1]]),
      limit_page_length: 100,
    });
    providers.value = Array.isArray(data) ? data : [];
  } catch (e) {
    providers.value = [];
  }

  // WI-001655: the AI Model catalog — picking a model implies its
  // credentials. Only USABLE models are offered: linked to credentials
  // that are enabled (same rule as the assistant's grounding); unlinked
  // catalog rows are managed in the desk until someone links them.
  try {
    const models = await frappeGet("/api/resource/AI Model", {
      fields: JSON.stringify(["name", "ai_provider_credentials"]),
      filters: JSON.stringify([["ai_provider_credentials", "is", "set"]]),
      limit_page_length: 100,
      order_by: "name asc",
    });
    const enabledCreds = new Set(providers.value.map((p) => p.name));
    catalogModels.value = (Array.isArray(models) ? models : []).filter(
      (m) => enabledCreds.has(m.ai_provider_credentials)
    );
  } catch (e) {
    catalogModels.value = [];
  }

  // Load selectable AI Agent Configurations for the seed dropdown.
  try {
    const cfgs = await frappeGet("/api/resource/AI Agent Configuration", {
      fields: JSON.stringify(["name", "agent_id"]),
      filters: JSON.stringify([["enabled", "=", 1]]),
      limit_page_length: 100,
      order_by: "name asc",
    });
    agentConfigs.value = Array.isArray(cfgs) ? cfgs : [];
  } catch (e) {
    agentConfigs.value = [];
  }

  // Load DocType names for the Context DocType autocomplete.
  try {
    const rows = await frappeRequest({
      url: "/api/method/frappe.client.get_list",
      params: {
        doctype: "DocType",
        fields: JSON.stringify(["name"]),
        limit_page_length: 0,
        order_by: "name asc",
      },
    });
    doctypeOptions.value = Array.isArray(rows) ? rows.map((r) => r.name) : [];
  } catch (e) {
    doctypeOptions.value = [];
  }

  // Read existing attrs from element
  const bo = rawElement().businessObject;
  const get = (attr) => bo.get(`spiffworkflow:${attr}`) ?? "";
  // Parse a numeric attr while preserving a legitimately-saved 0
  // (`parseX(...) || default` would replace a stored 0 with the default).
  const numOr = (attr, fallback, parse = parseFloat) => {
    const raw = get(attr);
    if (raw === "" || raw === null || raw === undefined) return fallback;
    const v = parse(raw);
    return Number.isFinite(v) ? v : fallback;
  };
  form.value = {
    aiAgentConfig: get("aiAgentConfig") || "",
    aiBackend: get("aiBackend") || "direct_api",
    aiProvider: get("aiProvider") || "",
    aiModel: get("aiModel") || "",
    aiOutputVariable: get("aiOutputVariable") || "ai_result",
    aiSystemPrompt: get("aiSystemPrompt") || "",
    aiUserPrompt: get("aiUserPrompt") || "",
    aiResponseFormat: get("aiResponseFormat") || "text",
    aiResponseSchema: get("aiResponseSchema") || "",
    aiTemperature: numOr("aiTemperature", 0.7),
    aiTopP: numOr("aiTopP", 1.0),
    aiMaxTokens: numOr("aiMaxTokens", 1024, parseInt),
    aiTimeout: numOr("aiTimeout", 30, parseInt),
    aiMaxRetries: numOr("aiMaxRetries", 2, parseInt),
    aiStopOnError: get("aiStopOnError") === "true",
    // Memory
    aiConversationStore: get("aiConversationStore") || "process_variable",
    aiContextMaxMessages: numOr("aiContextMaxMessages", 20, parseInt),
    aiLongTermMemory: get("aiLongTermMemory") === "true",
    aiMemoryScope: get("aiMemoryScope") || "Agent",
    // Back-compat: a legacy aiMemoryAutoWrite="true" now maps to "distilled"
    // (matching the dispatcher), so an old element reads as its effective mode.
    aiMemoryWriteMode:
      get("aiMemoryWriteMode") ||
      (get("aiMemoryAutoWrite") === "true" ? "distilled" : "off"),
    // WI-001793: these two live on the agent, but seed them from the diagram so
    // a map whose agent has not been migrated still shows its real setting.
    // They must exist on the form object — loadMemoryFromConfig only overlays
    // keys already present, and this assignment replaces form.value wholesale.
    aiMemoryDistillModel: get("aiMemoryDistillModel") || "",
    aiMemoryReconcileModel: get("aiMemoryReconcileModel") || "",
    // WI-001639: agent-owned, with no diagram fallback — this assignment
    // replaces form.value wholesale, so the keys must exist here or
    // loadStaticContextFromConfig has nothing to fill and the template binds
    // to undefined.
    aiExamples: [],
    aiGuardrails: [],
  };

  // Read the diagram's start-event trigger DocType — the process context the
  // prompts will run against — and ground selector turns with it.
  if (!triggerDoctype.value) {
    try {
      const defs = toRaw(props.modeler).getDefinitions();
      for (const rootEl of defs.rootElements || []) {
        for (const flowEl of rootEl.flowElements || []) {
          if (flowEl.$type !== "bpmn:StartEvent") continue;
          const trigger =
            flowEl.get?.("spiffworkflow:triggerDoctype") ||
            flowEl.$attrs?.["spiffworkflow:triggerDoctype"];
          if (trigger) {
            triggerDoctype.value = trigger;
            break;
          }
        }
        if (triggerDoctype.value) break;
      }
    } catch (e) { /* best effort */ }
  }

  // WI-001652: show the linked agent's lifecycle so "why can't I deploy"
  // is visible before the compile error says it.
  refreshLinkedAgentStatus();

  // WI-001793: the agent owns the memory settings — show its values, not the
  // diagram's stale copies, so Save can't write yesterday's config back.
  await loadMemoryFromConfig();

  // WI-001639: the agent owns examples and guard rails — show its rows, not an
  // empty pair of sections, so Save can't write a blank static context back.
  await loadStaticContextFromConfig();
  await loadScreening();
});

// Pull the linked configuration's current values into the form (WI-001637
// live link). The resolver returns shape-attribute keys (aiSystemPrompt,
// aiProvider, aiModel, aiTemperature, aiMaxTokens) that map directly onto our
// form fields. At run time the configuration is authoritative for these
// fields; editing them here and saving writes the changes back to it.
// WI-001793: memory settings are stored on the agent, not the diagram, so a
// linked configuration is the source of truth for them. The resolver hands back
// shape-attribute keys; only the toggle needs translating, because the doctype
// models it as Enabled / Disabled / blank (blank = inherit the diagram's older
// value) while the modal binds a checkbox.
const MEMORY_FORM_KEYS = [
  "aiConversationStore",
  "aiContextMaxMessages",
  "aiLongTermMemory",
  "aiMemoryScope",
  "aiMemoryWriteMode",
  "aiMemoryDistillModel",
  "aiMemoryReconcileModel",
];

function configValueToForm(key, val) {
  if (key !== "aiLongTermMemory") return val;
  return val === true || val === 1 || ["enabled", "true", "1"].includes(String(val).toLowerCase());
}

function applyConfigFields(fields, onlyKeys = null) {
  Object.entries(fields || {}).forEach(([key, val]) => {
    if (onlyKeys && !onlyKeys.includes(key)) return;
    if (key in form.value) form.value[key] = configValueToForm(key, val);
  });
}

// On open, overlay the linked agent's memory settings so the panel shows what
// will actually run. Scoped to memory on purpose: the other agent-level fields
// keep their existing "shape copy is the editing view" behaviour.
async function loadMemoryFromConfig() {
  if (!form.value.aiAgentConfig) return;
  try {
    const fields = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
      method: "POST",
      params: { config_name: form.value.aiAgentConfig },
    });
    applyConfigFields(fields, MEMORY_FORM_KEYS);
  } catch (e) {
    // Unreadable config — the shape's older values stay on screen, which is
    // also what dispatch will fall back to.
  }
}

async function onAgentConfigSelect() {
  const value = form.value.aiAgentConfig;
  if (value === "__create__") {
    // WI-001648: open the inline create panel instead of linking. A NEW
    // agent starts BLANK — carrying the task's prompts into the panel
    // confused more than it helped. Only the provider carries over
    // (harmless convenience, freely changeable).
    form.value.aiAgentConfig = "";
    newAgent.value = {
      ...emptyNewAgent(),
      ai_model: form.value.aiModel || "",
    };
    agentIdEdited.value = false;
    showCreateAgent.value = true;
    return;
  }
  refreshLinkedAgentStatus();
  // A real link (picked from the dropdown, or set by the assistant's
  // create flow) makes a still-open manual create panel stale — close it.
  if (value) showCreateAgent.value = false;
  if (!value) return;
  try {
    const fields = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
      method: "POST",
      params: { config_name: value },
    });
    applyConfigFields(fields);
    // WI-001639: the same read carries the static-context tables, so the
    // sections follow the newly linked agent rather than keeping the old
    // agent's rows on screen.
    form.value.aiExamples = Array.isArray(fields?.aiExamples) ? fields.aiExamples : [];
    form.value.aiGuardrails = Array.isArray(fields?.aiGuardrails) ? fields.aiGuardrails : [];
    staticContextLoaded.value = true;
    await loadScreening();
  } catch (e) {
    /* leave the current field values as-is if the seed lookup fails */
  }
}

// The designer's confirm no longer creates anything itself: it relays the
// approval into the conversation, and the AGENT calls its
// create_agent_configuration tool — so every creation is audited as a tool
// call on its AI Agent Run, and a chat approval typed in plain words works
// exactly the same way. The onefm.created_config event that follows a
// verified creation links the new agent on this shape (onAssistantAgentEvent).
async function createProposedAgent(onFail) {
  const panel = chatPanel.value;
  if (!panel) {
    const text =
      "⚠️ The assistant chat is not open — approve the proposal by replying in the chat instead.";
    if (onFail) onFail(text);
    else showNotice("Assistant chat not open", text);
    return;
  }
  panel.send("Approved — create the agent exactly as proposed.");
}

// onefm.created_config is proof of a verified record (the reply shaper only
// emits it after frappe.db.exists confirms the row): link it on this shape
// and pull its values into the form, same as picking it from the dropdown.
async function onAssistantAgentEvent({ name, value }) {
  if (name !== "onefm.created_config" || !value?.name) return;
  if (!agentConfigs.value.some((c) => c.name === value.name)) {
    agentConfigs.value.push({ name: value.name, agent_id: value.agent_id || "" });
  }
  form.value.aiAgentConfig = value.name;
  await onAgentConfigSelect();
}

// WI-001649 amendment: confirm the assistant's update proposal — same
// endpoint as the dialog's Save write-back (WI-001637): permission-checked,
// a Needs-Attention agent's waiting instance resumes on save, a Live chat
// agent re-provisions. If the changed config is the one linked on this shape,
// its fresh values are pulled back into the form and the badge refreshed.
async function applyProposedUpdate(m, onFail) {
  if (m.updateState === "applying") return;
  m.updateState = "applying";
  try {
    const res = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.update_agent_config_from_shape",
      method: "POST",
      params: {
        config_name: m.update.config_name,
        fields: JSON.stringify(m.update.fields),
      },
    });
    m.updateState = "applied";
    m.updateResult = res;
    if (form.value.aiAgentConfig === m.update.config_name) {
      await onAgentConfigSelect();
    }
  } catch (e) {
    m.updateState = null;
    const text =
      "⚠️ Could not apply the change: " +
      ((e?.messages && e.messages.length && e.messages.join("\n")) || e?.message || e);
    if (onFail) onFail(text);
    else showNotice("Changes not applied to the agent", text);
  }
}

// WI-001648: create the AI Agent Configuration from the dialog. The record is
// inserted as Chat + Draft with the user's own permissions; the AI Agent
// Creation Process starts on insert and takes it to Live. On success the new
// agent is linked on this shape and its values pulled into the form.
async function createAgent() {
  if (creatingAgent.value) return;
  if (!newAgent.value.agent_name.trim()) return showNotice("Missing information", "Agent name is required.");
  if (!newAgent.value.chat_mode_label.trim()) return showNotice("Missing information", "A chat mode label is required.");
  if (!newAgent.value.ai_model) return showNotice("Missing information", "Pick an AI Model — the provider follows from it.");
  creatingAgent.value = true;
  try {
    const payload = {
      ...newAgent.value,
      agent_id: newAgent.value.agent_id.trim() || scrubbedAgentId.value,
      sample_prompts: newAgent.value.sample_prompts.filter((sp) => (sp.prompt || "").trim()),
      enabled_skills: newAgent.value.ai_skills.filter((sk) => (sk.skill || "").trim()),
    };
    const res = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.create_agent_configuration",
      method: "POST",
      params: { payload: JSON.stringify(payload) },
    });
    agentConfigs.value.push({ name: res.name, agent_id: res.agent_id });
    form.value.aiAgentConfig = res.name;
    await onAgentConfigSelect();
    showCreateAgent.value = false;
    showNotice(
      "Agent created",
      `"${res.name}" created and linked to this task.\n` +
        (res.creation_instance
          ? `The AI Agent Creation Process is running (instance ${res.creation_instance}) — it will take the agent to Live.`
          : "The creation process did not start (model inactive?) — check the AI Agent Configuration record.")
    );
  } catch (e) {
    showNotice("Could not create the agent configuration", serverMessage(e));
  } finally {
    creatingAgent.value = false;
  }
}

// WI-001637 live link: on Save, write agent-level edits back to the linked
// AI Agent Configuration. Selector mode omits temperature — the selector
// dialog never shows it, so its form default must not clobber the record.
// Failure never blocks the shape save; the user is warned instead. A Live
// agent is automatically re-provisioned by the backend so its chat map picks
// up the change — silently: re-validation failures surface in deploy checks,
// not as a popup on every save.
async function writeBackToConfig() {
  if (!form.value.aiAgentConfig) return;
  // WI-001655: the MODEL is the agent's editable pick and writes back;
  // aiProvider is no longer sent — the provider is derived from the model.
  const fields = {
    aiModel: form.value.aiModel,
    aiSystemPrompt: form.value.aiSystemPrompt,
    aiMaxTokens: form.value.aiMaxTokens,
  };
  if (!isSelector.value) fields.aiTemperature = form.value.aiTemperature;
  // Screening is NOT sent here. It has its own writer (saveScreening, below),
  // and sending it from both places meant the resolver write landed second and
  // put the stale form value back — silently undoing whatever the user had just
  // picked in the Screening section. The editable copy lives on
  // screeningControls, not on form, so this endpoint has nothing current to say
  // about it. Creation is different and still goes through the resolver: the
  // agent has no record to read controls off yet.
  // WI-001793: memory is agent-level now, so it persists here rather than onto
  // the BPMN XML. The selector dialog has no memory section — sending its form
  // defaults would clobber the agent's real settings.
  if (!isSelector.value) {
    fields.aiConversationStore = form.value.aiConversationStore;
    fields.aiContextMaxMessages = form.value.aiContextMaxMessages;
    fields.aiLongTermMemory = form.value.aiLongTermMemory ? "Enabled" : "Disabled";
    fields.aiMemoryScope = form.value.aiLongTermMemory ? form.value.aiMemoryScope : "";
    fields.aiMemoryWriteMode = form.value.aiLongTermMemory ? form.value.aiMemoryWriteMode : "";
    fields.aiMemoryDistillModel = form.value.aiMemoryDistillModel || "";
    fields.aiMemoryReconcileModel = form.value.aiMemoryReconcileModel || "";
  }
  // WI-001639: examples and guard rails are agent-level, so they persist here
  // rather than onto the BPMN XML. Sent whole (the backend replaces the tables)
  // and only when they were read first — omitting the keys means "leave them".
  if (staticContextLoaded.value) {
    fields.aiSkills = form.value.aiSkills;
    fields.aiExamples = form.value.aiExamples;
    fields.aiGuardrails = form.value.aiGuardrails;
  }
  // Screening goes through security_api, which accepts ONLY screening fields —
  // keeping this endpoint from becoming a general writer for the whole agent.
  await saveScreening();
  try {
    await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.update_agent_config_from_shape",
      method: "POST",
      params: { config_name: form.value.aiAgentConfig, fields: JSON.stringify(fields) },
    });
  } catch (e) {
    showNotice(
      "Changes not applied to the agent",
      `The task was saved, but writing the changes back to "${form.value.aiAgentConfig}" failed:\n` +
        serverMessage(e) +
        "\n\nUpdate the AI Agent Configuration record directly if the change should apply to the agent."
    );
  }
}

async function save() {
  // WI-001650: every AI shape must be backed by an AI Agent Configuration —
  // raw provider setup is retired (the compile gate enforces the same rule).
  if (!form.value.aiAgentConfig) {
    showNotice(
      "Link an AI Agent Configuration",
      "Link an AI Agent Configuration before saving.\n" +
        "Pick an existing agent, use “+ Create new…”, or ask the assistant to " +
        "create one — setting up an AI task with a raw provider has been retired (WI-001650)."
    );
    return;
  }

  // WI-001655: the model comes from the linked agent's catalog pick. An
  // empty model here means the agent has none yet — fix it on the agent.
  if (!form.value.aiModel || !form.value.aiModel.trim()) {
    showNotice(
      "No model set",
      "No model is set. Pick an AI Model on the linked AI Agent Configuration " +
        "(or ask the assistant to change the model) — the provider follows from it."
    );
    return;
  }

  // Validate JSON schema if provided
  if (!isSelector.value && form.value.aiResponseFormat === "json" && form.value.aiResponseSchema) {
    try {
      JSON.parse(form.value.aiResponseSchema);
    } catch (e) {
      showNotice("Invalid Response Schema", "Response Schema is not valid JSON: " + e.message);
      return;
    }
  }

  const modeling = toRaw(props.modeler).get("modeling");
  const element = rawElement();
  const bo = element.businessObject;

  if (isSelector.value) {
    // Only the attributes the selector dispatch reads — never touch
    // serviceType/aiToolSources (owned by the properties panel) and never
    // write agent-only attrs onto the ad-hoc subprocess.
    modeling.updateModdleProperties(element, bo, {
      "spiffworkflow:aiAgentConfig": form.value.aiAgentConfig || undefined,
      "spiffworkflow:aiProvider": form.value.aiProvider || undefined,
      "spiffworkflow:aiModel": form.value.aiModel || undefined,
      "spiffworkflow:aiSystemPrompt": form.value.aiSystemPrompt || undefined,
      "spiffworkflow:aiUserPrompt": form.value.aiUserPrompt || undefined,
      "spiffworkflow:aiMaxTokens": String(form.value.aiMaxTokens),
      "spiffworkflow:aiTimeout": String(form.value.aiTimeout),
    });
    await writeBackToConfig();
    emit("close");
    return;
  }

  const patch = {
    "spiffworkflow:aiAgentConfig": form.value.aiAgentConfig || undefined,
    "spiffworkflow:aiBackend": form.value.aiBackend || undefined,
    "spiffworkflow:aiProvider": form.value.aiProvider || undefined,
    "spiffworkflow:aiModel": form.value.aiModel || undefined,
    "spiffworkflow:aiOutputVariable": form.value.aiOutputVariable || undefined,
    "spiffworkflow:aiSystemPrompt": form.value.aiSystemPrompt || undefined,
    "spiffworkflow:aiUserPrompt": form.value.aiUserPrompt || undefined,
    "spiffworkflow:aiResponseFormat": form.value.aiResponseFormat || undefined,
    "spiffworkflow:aiResponseSchema": form.value.aiResponseSchema || undefined,
    "spiffworkflow:aiTemperature": String(form.value.aiTemperature),
    "spiffworkflow:aiTopP": String(form.value.aiTopP),
    "spiffworkflow:aiMaxTokens": String(form.value.aiMaxTokens),
    "spiffworkflow:aiTimeout": String(form.value.aiTimeout),
    "spiffworkflow:aiMaxRetries": String(form.value.aiMaxRetries),
    "spiffworkflow:aiStopOnError": form.value.aiStopOnError ? "true" : undefined,
    // WI-001793: memory settings are NOT written here any more — they live on
    // the linked AI Agent Configuration (see writeBackToConfig). Existing
    // diagrams keep their aiMemory* / aiConversationStore attributes untouched;
    // dispatch reads the agent first and only falls through to them when the
    // agent leaves a field blank.
  };

  modeling.updateModdleProperties(element, bo, patch);
  await writeBackToConfig();
  emit("close");
}
</script>

<style scoped>
.ai-agent-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-agent-modal {
  background: white;
  border-radius: 8px;
  /* 560px form + the shared chat pane (WI-001672 sizing token) */
  width: calc(560px + var(--agui-chat-pane, 420px));
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

/* Left column */
.modal-main {
  flex: 1 1 560px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-height: 90vh;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e2e2e2;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 { margin: 0; font-size: 1rem; font-weight: 600; }
.close-btn { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: #7c7c7c; }
.close-btn:hover { color: #171717; }

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field-row { display: flex; flex-direction: column; gap: 4px; }
.field-row.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; align-items: start; }
/* Each cell inside a two-column row stacks its label + input just like a
   single-column .field-row, so the advanced settings line up consistently. */
.field-row.two-col > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.field-row label { font-size: 0.8rem; font-weight: 500; color: #374151; }
.field-row .hint { font-weight: 400; color: #9ca3af; }
.field-row input:not([type="checkbox"]),
.field-row select,
.field-row textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 0.85rem;
  font-family: inherit;
}
.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 500;
  color: #374151;
}
.checkbox-input {
  width: 16px;
  height: 16px;
  accent-color: #171717;
  cursor: pointer;
  flex-shrink: 0;
}
.field-hint {
  font-size: 0.75rem;
  color: #9ca3af;
  font-weight: 400;
}
.field-row textarea { resize: vertical; min-height: 80px; }
.field-row input:focus,
.field-row select:focus,
.field-row textarea:focus {
  outline: none;
  border-color: #171717;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
}

.field-group-title {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6b7280;
  padding-top: 4px;
  border-top: 1px solid #f3f4f6;
}

.modal-footer {
  padding: 12px 20px;
  border-top: 1px solid #e2e2e2;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn-cancel, .btn-save {
  padding: 7px 16px;
  border-radius: 5px;
  font-size: 0.85rem;
  cursor: pointer;
  border: none;
}
.btn-cancel { background: #f3f3f3; color: #525252; }
.btn-cancel:hover { background: #e2e2e2; }
.btn-save { background: #171717; color: white; }
.btn-save:hover { background: #171717; }

/* Right column — assistant */
.assistant-panel {
  /* Consistent-side decision (2026-08-08): chat LEFT, work surface RIGHT
     on every agent surface — Logix and Docu already sat this way. */
  order: -1;
  flex: 0 0 var(--agui-chat-pane, 340px);
  display: flex;
  flex-direction: column;
  background: #f8f8f8;
  border-right: 1px solid #e2e2e2;
  max-height: 90vh;
}

.assistant-disabled {
  padding: 24px 18px;
  font-size: 0.82rem;
  color: #7c7c7c;
  line-height: 1.5;
}

.assistant-agui-panel {
  flex: 1;
  min-height: 0;
  border-left: none; /* the pane already draws the divider */
}

.agent-rerun {
  margin-left: 6px;
  padding: 1px 8px;
  font-size: 11px;
  border: 1px solid var(--border-color, #d1d8dd);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}
.agent-rerun:hover:not(:disabled) {
  background: var(--fg-hover-color, #f4f5f6);
}
.agent-rerun:disabled {
  opacity: 0.6;
  cursor: default;
}

/* ── Linked agent lifecycle badge (WI-001652) ── */
.agent-status {
  display: inline-block;
  font-weight: 600;
  font-size: 11px;
  margin-right: 6px;
  padding: 1px 6px;
  border-radius: 10px;
}
.agent-status-live { color: #15803d; background: #dcfce7; }
.agent-status-bad { color: #b91c1c; background: #fee2e2; }
.agent-status-pending { color: #92400e; background: #fef3c7; }

/* ── Create-new-agent panel (WI-001648) ── */
.create-agent-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
  background: #f8f8f8;
}
.sample-prompt-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
/* WI-001639: one editable row of the agent's static context. Stacked rather
   than the grid the sample-prompt rows use — these fields are prose, and a
   guard rail or a worked example needs the full width to be readable. */
.static-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  margin-bottom: 8px;
  border: 1px solid var(--border-color, #d1d8dd);
  border-radius: 6px;
}
.static-row-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.static-row-num {
  margin-left: auto;
  font-size: 11px;
  opacity: 0.6;
}
.static-row-inline-label {
  font-size: 11px;
  font-weight: 600;
  opacity: 0.75;
}
/* Every input inside a row is captioned. The placeholders these replace
   vanished the moment anything was typed, leaving a filled-in example as three
   anonymous boxes with no way to tell the input from the expected output. */
.static-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.static-field-label {
  font-size: 11px;
  font-weight: 600;
  opacity: 0.75;
}
.static-field-label em {
  font-style: normal;
  font-weight: 400;
  opacity: 0.75;
}
.static-row-cat {
  max-width: 160px;
}
.create-agent-actions {
  flex-direction: row;
  justify-content: flex-end;
  gap: 8px;
}
</style>

<style>
/* frappe-ui dialogs portal to <body> with no z-index of their own; this
   modal's overlay sits at z-index 1000, which would bury them. Dialogs are
   always the topmost surface. */
.dialog-overlay {
  z-index: 2000;
}
</style>
