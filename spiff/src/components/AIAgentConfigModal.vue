<template>
  <div class="ai-agent-modal-overlay" @click.self="$emit('close')">
    <div class="ai-agent-modal">
      <!-- ============ LEFT: configuration form ============ -->
      <div class="modal-main">
        <div class="modal-header">
          <h3>Configure AI Agent Task</h3>
          <button class="close-btn" @click="$emit('close')">✕</button>
        </div>

        <div class="modal-body">
          <!-- Backend -->
          <div class="field-row">
            <label>Backend</label>
            <select v-model="form.aiBackend">
              <option value="direct_api">Direct API</option>
              <option value="antigravity">Google Antigravity SDK</option>
            </select>
          </div>

          <!-- AI Provider -->
          <div class="field-row">
            <label>AI Provider</label>
            <select v-model="form.aiProvider" @change="onProviderChange">
              <option value="">-- Select Provider --</option>
              <option v-for="p in providers" :key="p.name" :value="p.name">
                {{ p.provider_name }}
              </option>
            </select>
          </div>

          <!-- Model override -->
          <div class="field-row">
            <label>Model <span class="hint">(overrides provider default)</span></label>
            <input type="text" v-model="form.aiModel" placeholder="e.g. gpt-4o" />
          </div>

          <!-- Output variable -->
          <div class="field-row">
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

          <!-- Response format -->
          <div class="field-row">
            <label>Response Format</label>
            <select v-model="form.aiResponseFormat">
              <option value="text">Text</option>
              <option value="json">JSON</option>
            </select>
          </div>

          <!-- Response schema (only when JSON) -->
          <div class="field-row" v-if="form.aiResponseFormat === 'json'">
            <label>Response Schema <span class="hint">(JSON Schema)</span></label>
            <textarea v-model="form.aiResponseSchema" rows="4" placeholder='{"type":"object",...}' />
          </div>

          <div class="field-group-title">Advanced Settings</div>

          <!-- Temperature -->
          <div class="field-row two-col">
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

          <div class="field-row">
            <label>Max Retries</label>
            <input type="number" v-model.number="form.aiMaxRetries" min="0" max="10" />
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="$emit('close')">Cancel</button>
          <button class="btn-save" @click="save">Save</button>
        </div>
      </div>

      <!-- ============ RIGHT: assistant chat panel ============ -->
      <div class="assistant-panel">
        <div class="assistant-header">
          <span class="assistant-title">✦ AI Assistant</span>
          <span v-if="form.aiProvider" class="assistant-sub">via {{ providerLabel }}</span>
        </div>

        <!-- Disabled state: no provider selected yet -->
        <div v-if="!form.aiProvider" class="assistant-disabled">
          Select an AI Provider on the left to enable the assistant. It will use
          that provider to recommend prompts and settings for this task.
        </div>

        <template v-else>
          <!-- Context controls -->
          <div class="assistant-context">
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

          <!-- Messages -->
          <div ref="messagesEl" class="assistant-messages">
            <div v-if="!messages.length" class="assistant-empty">
              Describe what this AI Agent Task should do, and I'll recommend field
              values you can apply one by one.
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
            </div>

            <div v-if="loading" class="msg msg-assistant">
              <div class="msg-text typing">Thinking…</div>
            </div>
          </div>

          <!-- Input -->
          <div class="assistant-input">
            <textarea
              v-model="input"
              rows="2"
              placeholder="e.g. Summarise the employee's leave history and flag any policy breaches"
              :disabled="loading"
              @keydown.enter.exact.prevent="sendMessage"
            />
            <button class="assistant-send" :disabled="loading || !input.trim()" @click="sendMessage">
              Send
            </button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, toRaw } from "vue";
import { frappePost, frappeGet } from "@/bpmn/shared/frappeResource";

// bpmn-js elements must never be touched as Vue reactive proxies — the renderer
// reads non-configurable properties (e.g. labels) that a Proxy cannot return,
// throwing on re-render. Always unwrap to the raw element before using it.
function rawElement() {
  return toRaw(props.element);
}

const props = defineProps({
  element: { type: Object, required: true },
  modeler: { type: Object, required: true },
});

const emit = defineEmits(["close"]);

const providers = ref([]);

// Form state — defaults
const form = ref({
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
});

// ── Assistant state ───────────────────────────────────────────────────────
const messages = ref([]);          // { id, role, content, recommendations? }
const input = ref("");
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
    const rows = await frappeGet("/api/method/frappe.client.get_list", {
      doctype: dt,
      fields: JSON.stringify(["name"]),
      filters: q ? JSON.stringify([["name", "like", `%${q}%`]]) : undefined,
      limit_page_length: 20,
      order_by: "modified desc",
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

// When a provider is selected, fill the Model field from its Default Model.
// If the provider has no Default Model, leave the field untouched — the empty
// state is caught (and blocked) at save time.
function onProviderChange() {
  const p = providers.value.find((x) => x.name === form.value.aiProvider);
  if (p && p.default_model) {
    form.value.aiModel = p.default_model;
  }
}

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
  if (!requirement || loading.value || !form.value.aiProvider) return;

  // History = the conversation so far (before this turn).
  const history = messages.value
    .filter((m) => m.content)
    .map((m) => ({ role: m.role, content: m.content }));

  messages.value.push({ id: makeId(), role: "user", content: requirement });
  input.value = "";
  loading.value = true;
  scrollBottom();

  try {
    const res = await frappePost(
      "/api/method/one_bpmn.api.ai_assistant.recommend_ai_task_config",
      {
        provider: form.value.aiProvider,
        backend: form.value.aiBackend || "direct_api",
        requirement,
        context_doctype: contextDoctype.value.trim(),
        context_docname: contextDocname.value.trim(),
        history: JSON.stringify(history),
      }
    );

    if (res && res.ok) {
      messages.value.push({
        id: makeId(),
        role: "assistant",
        content: res.message || "Here are my recommendations.",
        recommendations: res.recommendations || {},
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
    const res = await fetch(
      "/api/resource/AI Provider?fields=[\"name\",\"provider_name\",\"default_model\"]&filters=[[\"enabled\",\"=\",1]]&limit=100"
    );
    const data = await res.json();
    providers.value = data.data || [];
  } catch (e) {
    providers.value = [];
  }

  // Load DocType names for the Context DocType autocomplete.
  try {
    const rows = await frappeGet("/api/method/frappe.client.get_list", {
      doctype: "DocType",
      fields: JSON.stringify(["name"]),
      limit_page_length: 0,
      order_by: "name asc",
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
  };
});

function save() {
  // Block save when no model can be resolved: the Model field is empty AND the
  // selected provider has no Default Model to fall back on at runtime.
  if (!form.value.aiModel || !form.value.aiModel.trim()) {
    const p = providers.value.find((x) => x.name === form.value.aiProvider);
    if (!p || !p.default_model) {
      alert(
        "No model is set. The selected AI Provider has no Default Model.\n" +
          "Set a Default Model on the AI Provider, or enter a Model here."
      );
      return;
    }
  }

  // Validate JSON schema if provided
  if (form.value.aiResponseFormat === "json" && form.value.aiResponseSchema) {
    try {
      JSON.parse(form.value.aiResponseSchema);
    } catch (e) {
      alert("Response Schema is not valid JSON: " + e.message);
      return;
    }
  }

  const modeling = toRaw(props.modeler).get("modeling");
  const element = rawElement();
  const bo = element.businessObject;

  const patch = {
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
  };

  modeling.updateModdleProperties(element, bo, patch);
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
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 { margin: 0; font-size: 1rem; font-weight: 600; }
.close-btn { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: #64748b; }
.close-btn:hover { color: #0f172a; }

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
.field-row input,
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
.field-row textarea { resize: vertical; min-height: 80px; }
.field-row input:focus,
.field-row select:focus,
.field-row textarea:focus {
  outline: none;
  border-color: #6366f1;
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
  border-top: 1px solid #e2e8f0;
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
.btn-cancel { background: #f1f5f9; color: #475569; }
.btn-cancel:hover { background: #e2e8f0; }
.btn-save { background: #6366f1; color: white; }
.btn-save:hover { background: #4f46e5; }

/* Right column — assistant */
.assistant-panel {
  flex: 0 0 340px;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  border-left: 1px solid #e2e8f0;
  max-height: 90vh;
}

.assistant-header {
  padding: 16px 18px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.assistant-title { font-size: 0.92rem; font-weight: 600; color: #4338ca; }
.assistant-sub { font-size: 0.72rem; color: #94a3b8; }

.assistant-disabled {
  padding: 24px 18px;
  font-size: 0.82rem;
  color: #64748b;
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
.ctx-row label { font-size: 0.72rem; font-weight: 500; color: #475569; }
.ctx-row .hint { font-weight: 400; color: #9ca3af; }
.ctx-row input {
  padding: 5px 7px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  font-size: 0.8rem;
  font-family: inherit;
}
.ctx-hint { font-size: 0.68rem; color: #94a3b8; line-height: 1.4; }

.ctx-autocomplete { position: relative; }
.ctx-autocomplete input { width: 100%; box-sizing: border-box; }
.ctx-autocomplete input:disabled {
  background: #f1f5f9;
  color: #94a3b8;
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
  color: #334155;
  cursor: pointer;
}
.ctx-dropdown li:hover { background: #eef2ff; color: #4338ca; }
.ctx-dropdown-status {
  position: absolute;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  padding: 6px 9px;
  font-size: 0.78rem;
  color: #94a3b8;
  background: #fff;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  z-index: 10;
}

.assistant-messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.assistant-empty { font-size: 0.8rem; color: #94a3b8; line-height: 1.5; }

.msg { max-width: 100%; }
.msg-text {
  font-size: 0.82rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-user .msg-text {
  background: #6366f1;
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
  border: 1px solid #e2e8f0;
  border-radius: 8px 8px 8px 2px;
  width: fit-content;
  max-width: 95%;
}
.msg-text.typing { color: #94a3b8; font-style: italic; }

.recs { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.rec {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 7px 9px;
}
.rec-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.rec-field { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; color: #6366f1; }
.rec-apply {
  border: none;
  background: #6366f1;
  color: #fff;
  font-size: 0.72rem;
  padding: 3px 10px;
  border-radius: 4px;
  cursor: pointer;
}
.rec-apply:hover { background: #4f46e5; }
.rec-apply:disabled { background: #cbd5e1; cursor: default; }
.rec-value {
  font-size: 0.78rem;
  color: #334155;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-input {
  border-top: 1px solid #e2e8f0;
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
.assistant-input textarea:focus { outline: none; border-color: #6366f1; }
.assistant-send {
  border: none;
  background: #6366f1;
  color: #fff;
  padding: 8px 14px;
  border-radius: 5px;
  font-size: 0.82rem;
  cursor: pointer;
}
.assistant-send:hover { background: #4f46e5; }
.assistant-send:disabled { background: #cbd5e1; cursor: default; }
</style>
