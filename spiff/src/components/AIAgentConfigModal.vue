<template>
  <div class="ai-agent-modal-overlay" @click.self="$emit('close')">
    <div class="ai-agent-modal">
      <div class="modal-header">
        <h3>Configure AI Agent Task</h3>
        <button class="close-btn" @click="$emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <!-- Backend -->
        <div class="field-row">
          <label>Backend</label>
          <select v-model="form.aiBackend">
            <option value="direct_api">Direct API (OpenAI-compatible)</option>
            <option value="antigravity">Google Antigravity SDK</option>
          </select>
        </div>

        <!-- AI Provider -->
        <div class="field-row">
          <label>AI Provider</label>
          <select v-model="form.aiProvider">
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
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";

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

// Load AI Providers from Frappe
onMounted(async () => {
  try {
    const res = await fetch(
      "/api/resource/AI Provider?fields=[\"name\",\"provider_name\"]&filters=[[\"enabled\",\"=\",1]]&limit=100"
    );
    const data = await res.json();
    providers.value = data.data || [];
  } catch (e) {
    providers.value = [];
  }

  // Read existing attrs from element
  const bo = props.element.businessObject;
  const get = (attr) => bo.get(`spiffworkflow:${attr}`) ?? "";
  form.value = {
    aiBackend: get("aiBackend") || "direct_api",
    aiProvider: get("aiProvider") || "",
    aiModel: get("aiModel") || "",
    aiOutputVariable: get("aiOutputVariable") || "ai_result",
    aiSystemPrompt: get("aiSystemPrompt") || "",
    aiUserPrompt: get("aiUserPrompt") || "",
    aiResponseFormat: get("aiResponseFormat") || "text",
    aiResponseSchema: get("aiResponseSchema") || "",
    aiTemperature: parseFloat(get("aiTemperature")) || 0.7,
    aiTopP: parseFloat(get("aiTopP")) || 1.0,
    aiMaxTokens: parseInt(get("aiMaxTokens")) || 1024,
    aiTimeout: parseInt(get("aiTimeout")) || 30,
    aiMaxRetries: parseInt(get("aiMaxRetries")) ?? 2,
  };
});

function save() {
  // Validate JSON schema if provided
  if (form.value.aiResponseFormat === "json" && form.value.aiResponseSchema) {
    try {
      JSON.parse(form.value.aiResponseSchema);
    } catch (e) {
      alert("Response Schema is not valid JSON: " + e.message);
      return;
    }
  }

  const modeling = props.modeler.get("modeling");
  const bo = props.element.businessObject;

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

  modeling.updateModdleProperties(props.element, bo, patch);
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
  width: 560px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
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
.field-row.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field-row label { font-size: 0.8rem; font-weight: 500; color: #374151; }
.field-row .hint { font-weight: 400; color: #9ca3af; }
.field-row input,
.field-row select,
.field-row textarea {
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
</style>
