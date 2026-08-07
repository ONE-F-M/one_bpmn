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
        <!-- WI-001674 mockup parity: in agent mode the panel's own titlebar
             (avatar + name + config-driven badge) is the header; the legacy
             purple header remains for selector mode only. "runs on its own
             credentials" now comes from chat_description (WI-001996). -->
        <div v-if="isSelector" class="assistant-header">
          <span class="assistant-title">✦ AI Assistant</span>
          <span class="assistant-sub">runs on its own credentials</span>
        </div>

        <!-- WI-001650: the assistant is always available — with no linked
             configuration yet it runs on its own credentials (WI-001623), so
             you can ask it to create the agent this task will link.
             (No wrapper <template> here: a bare template element is native
             HTML and Vue does not render its children.) -->
        <!-- Context controls -->
        <!-- WI-001674 follow-up: the assistant's toolbox includes schema and
             record lookups, so the manual Context DocType / Sample Record
             grounding is redundant in agent mode — it asks the platform
             itself. Selector mode still uses the manual grounding. -->
        <div v-if="isSelector" class="assistant-context">
            <div class="ctx-row">
              <label>Context DocType <span class="hint">(optional)</span></label>
              <div class="ctx-autocomplete">
                <input
                  type="text"
                  v-model="contextDoctype"
                  placeholder="e.g. Employee"
                  autocomplete="off"
                  @input="onDoctypeInput"
                  @focus="onDoctypeFocus"
                  @blur="onDoctypeBlur"
                />
                <ul v-if="showDoctypeDropdown && filteredDoctypes.length" class="ctx-dropdown">
                  <li
                    v-for="dt in filteredDoctypes"
                    :key="dt"
                    @mousedown.prevent="selectDoctype(dt)"
                  >
                    {{ dt }}
                  </li>
                </ul>
              </div>
            </div>
            <div class="ctx-row">
              <label>Sample Record <span class="hint">(optional)</span></label>
              <div class="ctx-autocomplete">
                <input
                  type="text"
                  v-model="contextDocname"
                  :placeholder="docnamePlaceholder"
                  :disabled="!doctypeResolved"
                  autocomplete="off"
                  @input="onDocnameInput"
                  @focus="onDocnameFocus"
                  @blur="onDocnameBlur"
                />
                <ul v-if="showDocnameDropdown && recordOptions.length" class="ctx-dropdown">
                  <li
                    v-for="r in recordOptions"
                    :key="r"
                    @mousedown.prevent="selectDocname(r)"
                  >
                    {{ r }}
                  </li>
                </ul>
                <div
                  v-else-if="showDocnameDropdown && recordLoading"
                  class="ctx-dropdown-status"
                >
                  Searching…
                </div>
              </div>
            </div>
            <div class="ctx-hint">
              The assistant reads this DocType's schema and one sample record (your
              permissions apply) to tailor the prompts.
            </div>
          </div>

          <!-- WI-001674: agent mode rides the shared AgentChatPanel — one
               transport (the AG-UI endpoint), typed events, cards from the
               registry. Replies can never render as raw JSON: the assistant's
               reply shaper parses the contract server-side. The legacy
               transcript below now serves ONLY selector mode, whose direct
               LLM path never went through invoke_agent. -->
          <AgentChatPanel
            v-if="!isSelector"
            ref="chatPanel"
            class="assistant-agui-panel"
            :agent-id="'ai_agent_assistant'"
            :conversation="assistantConversation"
            :context="assistantTurnContext"
            :cards="cardRegistry"
            variant="docked"
            @conversation="(c) => (assistantConversation = c)"
            @card-action="onAssistantCardAction"
          />

          <!-- Messages (selector mode only) -->
          <div v-if="isSelector" ref="messagesEl" class="assistant-messages">
            <div v-if="!messages.length" class="assistant-empty">
              <template v-if="isSelector">
                Describe the flow like you'd brief a new colleague — no technical
                terms needed, the diagram supplies those. I'll recommend prompts
                you can apply one by one.
              </template>
              <template v-else>
                Describe what this AI Agent Task should do, and I'll recommend field
                values you can apply one by one.
              </template>
            </div>

            <div
              v-for="m in messages"
              :key="m.id"
              :class="['msg', m.role === 'user' ? 'msg-user' : 'msg-assistant']"
            >
              <div v-if="m.content" class="msg-text">{{ m.content }}</div>

              <!-- Recommendation cards -->
              <div v-if="m.recommendations && Object.keys(m.recommendations).length" class="recs">
                <div
                  v-for="(value, key) in m.recommendations"
                  :key="key"
                  class="rec"
                >
                  <div class="rec-head">
                    <span class="rec-field">{{ fieldLabel(key) }}</span>
                    <button
                      class="rec-apply"
                      :disabled="isApplied(m.id, key)"
                      @click="applyRecommendation(m.id, key, value)"
                    >
                      {{ isApplied(m.id, key) ? "Applied ✓" : "Apply" }}
                    </button>
                  </div>
                  <div class="rec-value">{{ valuePreview(value) }}</div>
                </div>
              </div>

              <!-- New-agent proposal card (WI-001649). The assistant PROPOSES;
                   the designer confirms; only then is the record created (via
                   the same endpoint as the manual "+ Create new…" panel) and
                   the creation process takes it to Live. -->
              <div v-if="m.proposal" class="proposal">
                <div class="proposal-title">Create this agent?</div>
                <table class="proposal-fields">
                  <tbody>
                    <tr v-for="(value, key) in proposalRows(m.proposal)" :key="key">
                      <td class="proposal-key">{{ key }}</td>
                      <td class="proposal-value">{{ valuePreview(value) }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="m.proposalState === 'created'" class="proposal-done">
                  ✓ Created and linked{{ m.proposalResult?.creation_instance ? ` — creation process running (${m.proposalResult.creation_instance})` : "" }}
                </div>
                <div v-else-if="m.proposalState === 'dismissed'" class="proposal-done">Dismissed — nothing was created.</div>
                <div v-else class="proposal-actions">
                  <button class="btn-cancel" :disabled="m.proposalState === 'creating'" @click="m.proposalState = 'dismissed'">Dismiss</button>
                  <button class="btn-save" :disabled="m.proposalState === 'creating'" @click="createProposedAgent(m)">
                    {{ m.proposalState === "creating" ? "Creating…" : "Create & link" }}
                  </button>
                </div>
              </div>

              <!-- Update-existing-agent proposal card (WI-001649 amendment).
                   Confirming calls the WI-001637 write-back endpoint — the
                   assistant itself never writes. -->
              <div v-if="m.update" class="proposal">
                <div class="proposal-title">Apply this change to {{ m.update.config_name }}?</div>
                <table class="proposal-fields">
                  <tbody>
                    <tr v-for="(value, key) in m.update.fields" :key="key">
                      <td class="proposal-key">{{ fieldLabel(key) }}</td>
                      <td class="proposal-value">{{ valuePreview(value) }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="m.updateState === 'applied'" class="proposal-done">
                  ✓ Applied — {{ (m.updateResult?.updated || []).join(", ") || "no fields changed" }}{{ m.updateResult?.reprovisioned ? " — the agent is re-provisioning (validate → Live)" : "" }}
                </div>
                <div v-else-if="m.updateState === 'dismissed'" class="proposal-done">Dismissed — nothing was changed.</div>
                <div v-else class="proposal-actions">
                  <button class="btn-cancel" :disabled="m.updateState === 'applying'" @click="m.updateState = 'dismissed'">Dismiss</button>
                  <button class="btn-save" :disabled="m.updateState === 'applying'" @click="applyProposedUpdate(m)">
                    {{ m.updateState === "applying" ? "Applying…" : "Apply & save" }}
                  </button>
                </div>
              </div>
            </div>

            <div v-if="loading" class="msg msg-assistant">
              <div class="msg-text typing">Thinking…</div>
            </div>
          </div>

          <!-- Input (selector mode only — the panel owns the agent-mode composer) -->
          <div v-if="isSelector" class="assistant-input-wrap">
            <!-- Tips popover, toggled by the bulb below -->
            <div v-if="showTips" class="assistant-tips assistant-tips-popover">
              <div class="assistant-tips-title">
                💡 {{ isSelector ? "Tips for a good description" : "Tips for a good prompt" }}
                <button class="assistant-tips-close" title="Close" @click="showTips = false">✕</button>
              </div>
              <ul v-if="isSelector">
                <li><strong>What to check first</strong> — e.g. "first see if the ticket mentions one of their orders"</li>
                <li><strong>How to decide between paths</strong> — e.g. "if it's about an order… otherwise…"</li>
                <li><strong>Who handles each path</strong> — e.g. "the order team handles it, or normal support"</li>
                <li><strong>What "finished" looks like</strong> — e.g. "the customer got a reply and the ticket is closed"</li>
              </ul>
              <ul v-else>
                <li><strong>What it should read</strong> — which parts of the document matter</li>
                <li><strong>What it should produce</strong> — a summary, a decision, a value for a field</li>
                <li><strong>What format</strong> — plain text, or structured data for a gateway to route on</li>
              </ul>
            </div>
            <div class="assistant-input">
              <button
                class="assistant-tips-toggle"
                :class="{ active: showTips }"
                :title="isSelector ? 'Tips for a good description' : 'Tips for a good prompt'"
                @click="showTips = !showTips"
              >💡</button>
              <textarea
                v-model="input"
                rows="2"
                :placeholder="isSelector
                  ? 'e.g. First check if the ticket is about an order. If it is, the order team handles it; otherwise support does. Either way the customer gets a reply, then close the ticket.'
                  : 'e.g. Summarise the employee\'s leave history and flag any policy breaches'"
                :disabled="loading"
                @keydown.enter.exact.prevent="sendMessage"
              />
              <button class="assistant-send" :disabled="loading || !input.trim()" @click="sendMessage">
                Send
              </button>
            </div>
          </div>
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
import { ref, computed, onMounted, onUnmounted, nextTick, toRaw } from "vue";
import { Dialog, frappeRequest } from "frappe-ui";
import { frappeGet } from "@/bpmn/shared/frappeResource";
// WI-001674: agent mode chats through the shared panel + card registry.
import { AgentChatPanel } from "@/components/chat";
import { cardRegistry } from "@/components/chat/cards/registry";

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

// Fields the selector dispatch actually consumes (ai_task_selector.py) —
// assistant recommendations outside this set are dropped in selector mode.
const SELECTOR_FIELDS = [
  "aiProvider",
  "aiModel",
  "aiSystemPrompt",
  "aiUserPrompt",
  "aiMaxTokens",
  "aiTimeout",
];

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

// Form state — defaults
const form = ref({
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
});

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
const messages = ref([]);
const assistantConversation = ref(""); // Chat Conversation driving the dialog (WI-001623)          // { id, role, content, recommendations? }
const chatPanel = ref(null);

// WI-001674: the modal sends RAW grounding refs; the server-side context
// builder (ai_assistant.build_assistant_turn_context) assembles the map's
// dialog_context from them — schema/sample reads stay permission-checked
// server-side, exactly as the legacy path did.
const assistantTurnContext = computed(() => ({
  assistant_dialog: {
    linked_config: form.value.aiAgentConfig || "",
    current_config: JSON.stringify({
      aiModel: form.value.aiModel,
      aiSystemPrompt: form.value.aiSystemPrompt,
      aiUserPrompt: form.value.aiUserPrompt,
      aiOutputVariable: form.value.aiOutputVariable,
      aiResponseFormat: form.value.aiResponseFormat,
    }),
  },
}));

// WI-001674: cards render and request — the HOST applies. The panel re-emits
// card actions here; each maps onto the SAME handlers/endpoints the legacy
// cards used, so permission checks and the creation process are identical.
async function onAssistantCardAction({ name, action, value }) {
  if (action === "dismiss") return;
  if (action === "confirm-create" && name === "onefm.proposed_config") {
    await createProposedAgent({ proposal: value.proposal, proposalState: null });
    return;
  }
  if (action === "apply-fields" && name === "onefm.proposed_update") {
    const fields = value.fields || {};
    // A proposed update to an EXISTING config goes through the WI-001637
    // write-back; plain recommendations apply onto the open form.
    if (fields.config_name) {
      await applyProposedUpdate({ update: fields, updateState: null });
    } else {
      for (const [key, val] of Object.entries(fields)) {
        applyRecommendation(null, key, val);
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
const input = ref("");
const showTips = ref(false);
const loading = ref(false);
const contextDoctype = ref("");
const contextDocname = ref("");
const messagesEl = ref(null);

// ── DocType / Sample Record autocomplete ─────────────────────────────────────
const doctypeOptions = ref([]);          // all DocType names (loaded on mount)
const showDoctypeDropdown = ref(false);
const recordOptions = ref([]);           // matching record names for chosen DocType
const showDocnameDropdown = ref(false);
const recordLoading = ref(false);
let recordSearchTimer = null;
let recordSearchSeq = 0;

// Dropdown only lists matches once the user has typed something.
const filteredDoctypes = computed(() => {
  const q = contextDoctype.value.trim().toLowerCase();
  if (!q) return [];
  return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
});

// Sample Record search is only meaningful once the typed DocType is a real one.
const doctypeResolved = computed(() =>
  doctypeOptions.value.includes(contextDoctype.value.trim())
);

const docnamePlaceholder = computed(() =>
  doctypeResolved.value ? "latest record if blank" : "select a DocType first"
);

function onDoctypeInput() {
  showDoctypeDropdown.value = true;
  // The DocType changed, so any previously chosen Sample Record no longer applies.
  contextDocname.value = "";
  recordOptions.value = [];
  showDocnameDropdown.value = false;
}
function onDoctypeFocus() {
  // Show again only if there's already typed text (never on an empty field).
  if (contextDoctype.value.trim()) showDoctypeDropdown.value = true;
}
function onDoctypeBlur() {
  // Delay so a mousedown on an option registers before the list hides.
  setTimeout(() => {
    showDoctypeDropdown.value = false;
  }, 150);
}
function selectDoctype(dt) {
  contextDoctype.value = dt;
  showDoctypeDropdown.value = false;
  contextDocname.value = "";
  recordOptions.value = [];
}

function onDocnameInput() {
  if (!doctypeResolved.value) return;
  showDocnameDropdown.value = true;
  queueRecordSearch();
}
function onDocnameFocus() {
  if (doctypeResolved.value) {
    showDocnameDropdown.value = true;
    queueRecordSearch();
  }
}
function onDocnameBlur() {
  setTimeout(() => {
    showDocnameDropdown.value = false;
  }, 150);
}
function selectDocname(name) {
  contextDocname.value = name;
  showDocnameDropdown.value = false;
}

function queueRecordSearch() {
  clearTimeout(recordSearchTimer);
  recordSearchTimer = setTimeout(runRecordSearch, 250);
}

// Query records of the currently selected DocType, filtered by the typed text.
async function runRecordSearch() {
  const dt = contextDoctype.value.trim();
  if (!doctypeOptions.value.includes(dt)) {
    recordOptions.value = [];
    return;
  }
  const q = contextDocname.value.trim();
  const seq = ++recordSearchSeq;
  recordLoading.value = true;
  try {
    const rows = await frappeRequest({
      url: "/api/method/frappe.client.get_list",
      params: {
        doctype: dt,
        fields: JSON.stringify(["name"]),
        filters: q ? JSON.stringify([["name", "like", `%${q}%`]]) : undefined,
        limit_page_length: 20,
        order_by: "modified desc",
      },
    });
    if (seq !== recordSearchSeq) return; // a newer search superseded this one
    recordOptions.value = Array.isArray(rows) ? rows.map((r) => r.name) : [];
  } catch (e) {
    if (seq === recordSearchSeq) recordOptions.value = [];
  } finally {
    if (seq === recordSearchSeq) recordLoading.value = false;
  }
}
const appliedKeys = ref(new Set()); // "<msgId>:<field>"

// Human-readable labels for recommendation fields (keys match form keys).
const FIELD_LABELS = {
  aiProvider: "AI Provider",
  aiBackend: "Backend",
  aiModel: "Model",
  aiOutputVariable: "Output Variable",
  aiSystemPrompt: "System Prompt",
  aiUserPrompt: "User Prompt",
  aiResponseFormat: "Response Format",
  aiResponseSchema: "Response Schema",
  aiTemperature: "Temperature",
  aiTopP: "Top P",
  aiMaxTokens: "Max Tokens",
  aiTimeout: "Timeout (s)",
  aiMaxRetries: "Max Retries",
};

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

function makeId() {
  return Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function fieldLabel(key) {
  return FIELD_LABELS[key] || key;
}

function valuePreview(value) {
  let str = typeof value === "string" ? value : JSON.stringify(value);
  str = (str || "").trim();
  return str.length > 240 ? str.slice(0, 240) + "…" : str;
}

function isApplied(msgId, key) {
  return appliedKeys.value.has(`${msgId}:${key}`);
}

function scrollBottom() {
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
  });
}

function applyRecommendation(msgId, key, value) {
  if (NUMERIC_FIELDS.includes(key)) {
    const n = Number(value);
    if (Number.isFinite(n)) form.value[key] = n;
  } else {
    form.value[key] = String(value);
  }
  // Switch the format toggle on so a JSON schema suggestion is visible.
  appliedKeys.value = new Set(appliedKeys.value).add(`${msgId}:${key}`);
}

async function sendMessage() {
  const requirement = input.value.trim();
  // WI-001650: no provider requirement — with nothing linked yet the server
  // falls back to the assistant's own credentials (WI-001623), so the chat
  // can be used to create the very first configuration for this task.
  if (!requirement || loading.value) return;

  // History = the conversation so far (before this turn).
  const history = messages.value
    .filter((m) => m.content)
    .map((m) => ({ role: m.role, content: m.content }));

  messages.value.push({ id: makeId(), role: "user", content: requirement });
  input.value = "";
  loading.value = true;
  scrollBottom();

  // Selector mode: ship the LIVE diagram (the saved model may be stale while
  // the designer edits) plus the current drafts so the assistant proposes
  // prompts that reference real shapes and refines instead of restarting.
  let diagramPayload = {};
  if (isSelector.value) {
    try {
      const { xml } = await toRaw(props.modeler).saveXML({ format: false });
      diagramPayload = {
        mode: "selector",
        bpmn_xml: xml,
        element_id: rawElement().businessObject?.id || rawElement().id || "",
        process_model: window.__ONE_BPMN_CURRENT_MODEL__ || "",
        current_config: JSON.stringify({
          aiModel: form.value.aiModel,
          aiSystemPrompt: form.value.aiSystemPrompt,
          aiUserPrompt: form.value.aiUserPrompt,
        }),
      };
    } catch (e) {
      console.warn("[AI assistant] could not serialize diagram:", e);
    }
  }

  try {
    const res = await frappeRequest({
      url: "/api/method/one_bpmn.api.ai_assistant.recommend_ai_task_config",
      method: "POST",
      params: {
        provider: form.value.aiProvider,
        backend: form.value.aiBackend || "direct_api",
        requirement,
        context_doctype: contextDoctype.value.trim(),
        context_docname: contextDocname.value.trim(),
        history: JSON.stringify(history),
        // WI-001649 amendment: the linked config is the default target for
        // "change this agent…" requests — no interrogation needed.
        linked_config: form.value.aiAgentConfig || "",
        // WI-001623: the dialog IS a chat-platform conversation — first send
        // creates it; later sends continue it (history lives server-side).
        conversation: assistantConversation.value || "",
        ...diagramPayload,
      },
    });

    if (res && res.ok) {
      if (res.conversation) assistantConversation.value = res.conversation;
      let recommendations = res.recommendations || {};
      if (isSelector.value) {
        // Drop suggestions for fields the selector doesn't have
        // (response schema, output variable, sampling params, …).
        recommendations = Object.fromEntries(
          Object.entries(recommendations).filter(([key]) => SELECTOR_FIELDS.includes(key))
        );
      }
      messages.value.push({
        id: makeId(),
        role: "assistant",
        content: res.message || "Here are my recommendations.",
        recommendations,
        // WI-001649: a complete new-agent proposal the designer can confirm.
        proposal: !isSelector.value && res.proposed_config ? res.proposed_config : null,
        proposalState: null, // null | "creating" | "created" | "dismissed"
        proposalResult: null,
        // WI-001649 amendment: a proposed change to an EXISTING agent.
        update: !isSelector.value && res.proposed_update ? res.proposed_update : null,
        updateState: null, // null | "applying" | "applied" | "dismissed"
        updateResult: null,
      });
    } else {
      const err = (res && (res.message || res.error_code)) || "The assistant request failed.";
      messages.value.push({ id: makeId(), role: "assistant", content: `⚠️ ${err}` });
    }
  } catch (e) {
    messages.value.push({
      id: makeId(),
      role: "assistant",
      content: "⚠️ Could not reach the assistant. Check your connection and try again.",
    });
  } finally {
    loading.value = false;
    scrollBottom();
  }
}

// ── Load providers + existing element config ────────────────────────────────
onMounted(async () => {
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
  };

  // Pre-fill the assistant's context DocType from the diagram's start-event
  // trigger — the process context the prompts will run against.
  if (!contextDoctype.value) {
    try {
      const defs = toRaw(props.modeler).getDefinitions();
      for (const rootEl of defs.rootElements || []) {
        for (const flowEl of rootEl.flowElements || []) {
          if (flowEl.$type !== "bpmn:StartEvent") continue;
          const triggerDoctype =
            flowEl.get?.("spiffworkflow:triggerDoctype") ||
            flowEl.$attrs?.["spiffworkflow:triggerDoctype"];
          if (triggerDoctype) {
            contextDoctype.value = triggerDoctype;
            break;
          }
        }
        if (contextDoctype.value) break;
      }
    } catch (e) { /* best effort */ }
  }

  // WI-001652: show the linked agent's lifecycle so "why can't I deploy"
  // is visible before the compile error says it.
  refreshLinkedAgentStatus();

  // WI-001793: the agent owns the memory settings — show its values, not the
  // diagram's stale copies, so Save can't write yesterday's config back.
  await loadMemoryFromConfig();
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
  } catch (e) {
    /* leave the current field values as-is if the seed lookup fails */
  }
}

// WI-001649: human-readable rows for the proposal card.
const PROPOSAL_LABELS = {
  agent_name: "Name",
  agent_id: "Agent ID",
  chat_mode_label: "Chat mode label",
  ai_model: "Model (provider follows)",
  system_prompt: "System prompt",
  description: "Description",
};
function proposalRows(proposal) {
  const rows = {};
  for (const [key, label] of Object.entries(PROPOSAL_LABELS)) {
    if (proposal[key]) rows[label] = proposal[key];
  }
  if (Array.isArray(proposal.sample_prompts) && proposal.sample_prompts.length) {
    rows["Sample prompts"] = proposal.sample_prompts.map((sp) => sp.prompt).join(" • ");
  }
  // WI-001639: examples and guard rails become part of the agent's frozen
  // static context, so the designer must SEE them before confirming — a
  // proposal card that hides them would create rules nobody agreed to.
  if (Array.isArray(proposal.examples) && proposal.examples.length) {
    rows["Examples"] = proposal.examples.map((ex) => ex.input).join(" • ");
  }
  if (Array.isArray(proposal.guardrails) && proposal.guardrails.length) {
    rows["Guard rails"] = proposal.guardrails
      .map((g) => (g.category ? `[${g.category}] ${g.guardrail}` : g.guardrail))
      .join(" • ");
  }
  return rows;
}

// WI-001649: confirm the assistant's proposal — same endpoint as the manual
// "+ Create new…" panel, so permission checks and the Chat+Draft insert (which
// starts the creation process) are identical. On success the new agent is
// linked on this shape and its values pulled into the form.
async function createProposedAgent(m) {
  if (m.proposalState === "creating") return;
  m.proposalState = "creating";
  try {
    const res = await frappeRequest({
      url: "/api/method/one_bpmn.agents.agent_config_resolver.create_agent_configuration",
      method: "POST",
      params: { payload: JSON.stringify(m.proposal) },
    });
    agentConfigs.value.push({ name: res.name, agent_id: res.agent_id });
    form.value.aiAgentConfig = res.name;
    await onAgentConfigSelect();
    m.proposalState = "created";
    m.proposalResult = res;
  } catch (e) {
    m.proposalState = null;
    messages.value.push({
      id: makeId(),
      role: "assistant",
      content: "⚠️ Could not create the agent: " + (e?.message || e),
    });
    scrollBottom();
  }
}

// WI-001649 amendment: confirm the assistant's update proposal — same
// endpoint as the dialog's Save write-back (WI-001637): permission-checked,
// a Needs-Attention agent's waiting instance resumes on save, a Live chat
// agent re-provisions. If the changed config is the one linked on this shape,
// its fresh values are pulled back into the form and the badge refreshed.
async function applyProposedUpdate(m) {
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
    messages.value.push({
      id: makeId(),
      role: "assistant",
      content: "⚠️ Could not apply the change: " + (e?.message || e),
    });
    scrollBottom();
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
  width: 920px;
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
  flex: 0 0 340px;
  display: flex;
  flex-direction: column;
  background: #f8f8f8;
  border-left: 1px solid #e2e2e2;
  max-height: 90vh;
}

.assistant-header {
  padding: 16px 18px;
  border-bottom: 1px solid #e2e2e2;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.assistant-title { font-size: 0.92rem; font-weight: 600; color: #383838; }
.assistant-sub { font-size: 0.72rem; color: #999999; }

.assistant-disabled {
  padding: 24px 18px;
  font-size: 0.82rem;
  color: #7c7c7c;
  line-height: 1.5;
}

.assistant-context {
  padding: 12px 16px;
  border-bottom: 1px solid #eef2f7;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ctx-row { display: flex; flex-direction: column; gap: 3px; }
.ctx-row label { font-size: 0.72rem; font-weight: 500; color: #525252; }
.ctx-row .hint { font-weight: 400; color: #9ca3af; }
.ctx-row input {
  padding: 5px 7px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 0.8rem;
  font-family: inherit;
}
.ctx-hint { font-size: 0.68rem; color: #999999; line-height: 1.4; }

.ctx-autocomplete { position: relative; }
.ctx-autocomplete input { width: 100%; box-sizing: border-box; }
.ctx-autocomplete input:disabled {
  background: #f3f3f3;
  color: #999999;
  cursor: not-allowed;
}
.ctx-dropdown {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  max-height: 200px;
  overflow-y: auto;
  z-index: 10;
}
.ctx-dropdown li {
  padding: 5px 9px;
  font-size: 0.8rem;
  color: #383838;
  cursor: pointer;
}
.ctx-dropdown li:hover { background: #f3f3f3; color: #383838; }
.ctx-dropdown-status {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  padding: 6px 9px;
  font-size: 0.78rem;
  color: #999999;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  z-index: 10;
}

.assistant-agui-panel {
  flex: 1;
  min-height: 0;
  border-left: none; /* the pane already draws the divider */
}
.assistant-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.assistant-empty { font-size: 0.8rem; color: #999999; line-height: 1.5; }

/* "Tips for a good prompt" callout — opened from the 💡 toggle by the input */
.assistant-tips {
  padding: 10px 12px;
  background: #f8f8f8;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
  color: #7c7c7c;
  font-size: 0.8rem;
  line-height: 1.5;
}
.assistant-input-wrap { position: relative; }
.assistant-tips-popover {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  right: 0;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  z-index: 10;
}
.assistant-tips-close {
  float: right;
  border: none;
  background: transparent;
  color: #999999;
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0 2px;
}
.assistant-tips-close:hover { color: #525252; }
.assistant-tips-toggle {
  align-self: flex-end;
  border: 1px solid #e2e2e2;
  background: #f8f8f8;
  border-radius: 8px;
  padding: 6px 8px;
  cursor: pointer;
  font-size: 0.85rem;
  line-height: 1;
}
.assistant-tips-toggle:hover { background: #f3f3f3; }
.assistant-tips-toggle.active { background: #ede9fe; border-color: #c4b5fd; }
.assistant-tips-title {
  font-weight: 600;
  color: #525252;
  margin-bottom: 6px;
}
.assistant-tips ul {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.assistant-tips li strong { color: #525252; }

.msg { max-width: 100%; }
.msg-text {
  font-size: 0.82rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-user .msg-text {
  background: #171717;
  color: #fff;
  padding: 8px 10px;
  border-radius: 8px 8px 2px 8px;
  align-self: flex-end;
  margin-left: auto;
  width: fit-content;
  max-width: 90%;
}
.msg-assistant .msg-text {
  background: #fff;
  color: #1f2937;
  padding: 8px 10px;
  border: 1px solid #e2e2e2;
  border-radius: 8px 8px 8px 2px;
  width: fit-content;
  max-width: 95%;
}
.msg-text.typing { color: #999999; font-style: italic; }

.recs { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.rec {
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 6px;
  padding: 7px 9px;
}
.rec-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.rec-field { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; color: #171717; }
.rec-apply {
  border: none;
  background: #171717;
  color: #fff;
  font-size: 0.72rem;
  padding: 3px 10px;
  border-radius: 4px;
  cursor: pointer;
}
.rec-apply:hover { background: #171717; }
.rec-apply:disabled { background: #c7c7c7; cursor: default; }
.rec-value {
  font-size: 0.78rem;
  color: #383838;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-input {
  border-top: 1px solid #e2e2e2;
  padding: 10px 12px;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.assistant-input textarea {
  flex: 1;
  resize: none;
  padding: 6px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 0.82rem;
  font-family: inherit;
}
.assistant-input textarea:focus { outline: none; border-color: #171717; }
.assistant-send {
  border: none;
  background: #171717;
  color: #fff;
  padding: 8px 14px;
  border-radius: 5px;
  font-size: 0.82rem;
  cursor: pointer;
}
.assistant-send:hover { background: #171717; }
.assistant-send:disabled { background: #c7c7c7; cursor: default; }

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

/* ── Assistant new-agent proposal card (WI-001649) ── */
.proposal {
  margin-top: 8px;
  padding: 10px;
  border: 1px solid #c7d2fe;
  border-radius: 8px;
  background: #f3f3f3;
}
.proposal-title {
  font-weight: 600;
  font-size: 13px;
  color: #3730a3;
  margin-bottom: 6px;
}
.proposal-fields {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.proposal-key {
  color: #171717;
  font-weight: 600;
  padding: 2px 8px 2px 0;
  white-space: nowrap;
  vertical-align: top;
}
.proposal-value {
  color: #1e293b;
  padding: 2px 0;
  word-break: break-word;
}
.proposal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.proposal-done {
  margin-top: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #15803d;
}

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
