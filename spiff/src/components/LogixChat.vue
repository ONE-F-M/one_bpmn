<template>
	<Teleport to="body">
		<!-- Scrim -->
		<div v-if="modelValue" class="lx-scrim" @click.self="handleClose">
			<!-- Chat window -->
			<div class="lx-window" role="dialog" aria-modal="true" aria-label="Logix AI Assistant">

				<!-- ── Header ─────────────────────────────────────────────── -->
				<div class="lx-header">
					<div class="lx-header-left">
						<span class="lx-logo-icon" aria-hidden="true">
							<svg viewBox="0 0 24 24" fill="none">
								<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="currentColor"/>
							</svg>
						</span>
						<span class="lx-title">Logix</span>
						<span v-if="elementLabel" class="lx-context-chip" :title="elementLabel">
							{{ elementLabel }}
						</span>
					</div>
					<div class="lx-header-actions">
						<button class="lx-icon-btn" title="New conversation" @click="resetConversation">
							<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
								<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
							</svg>
						</button>
						<button class="lx-icon-btn lx-close-btn" title="Close" @click="handleClose">
							<svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
								<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
							</svg>
						</button>
					</div>
				</div>

				<!-- ── Chat (WI-001677: the shared AgentChatPanel) ──────────
				     Same implementation as the LogixCanvas split view — the two
				     surfaces now share one panel. Script changes arrive as
				     onefm.script_diff cards; the create-and-link naming dialog
				     below is this surface's apply target. -->
				<AgentChatPanel
					v-if="modelValue"
					:key="panelKey"
					class="lx-agui-panel"
					agent-id="logix_agent"
					variant="modal"
					:context="logixTurnContext"
					:cards="cardRegistry"
					@card-action="onLogixCardAction"
				/>

		<div v-if="showApplyDialog" class="lx-scrim lx-apply-scrim" @click.self="showApplyDialog = false">
			<div class="lx-apply-window" role="dialog" aria-modal="true">
				<div class="lx-apply-header">
					<span class="lx-apply-title">Apply Script</span>
				</div>
				<div class="lx-apply-body">
					<p class="lx-apply-hint">
						Enter a name for this Server Script. It will be created and linked to the Script Task.
					</p>
					<div class="lx-apply-field">
						<label class="lx-apply-label">Script Name <span class="lx-required">*</span></label>
						<input
							ref="applyNameInput"
							v-model="applyScriptName"
							class="lx-apply-input"
							placeholder="e.g. Validate Employee Shift"
							@keydown.enter="applyScript"
						/>
					</div>
					<div v-if="applyError" class="lx-apply-error">{{ applyError }}</div>
				</div>
				<div class="lx-apply-actions">
					<button class="lx-btn-text" @click="showApplyDialog = false">Cancel</button>
					<button
						class="lx-btn-filled"
						@click="applyScript"
						:disabled="!applyScriptName.trim() || applyLoading"
					>
						<span v-if="applyLoading" class="lx-spinner"></span>
						{{ applyLoading ? 'Creating…' : 'Create & Link' }}
					</button>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { frappeRequest } from "frappe-ui";
// WI-001677: both Logix surfaces share the panel + card registry.
import { AgentChatPanel } from "@/components/chat";
import { cardRegistry } from "@/components/chat/cards/registry";

const props = defineProps({
	modelValue:    { type: Boolean, default: false },
	element:       { type: Object,  default: null },
	scriptType:    { type: String,  default: "bpmn:script" },
	currentScript: { type: String,  default: "" },
	eventBus:      { type: Object,  default: null },
});

const emit = defineEmits(["update:modelValue"]);

// ── WI-001677 wiring ──────────────────────────────────────────────────
// The shared panel owns transcript/composer/lifecycle; this surface owns
// what card actions mean: CREATE opens the create-and-link naming dialog
// (prefilled from the card's suggested name), MODIFY updates the linked
// script in place — both ending on the same eventBus handoff the legacy
// handlers used — and test cases run against the linked script.

// Bumping the key remounts the panel: the unmount ends the old conversation
// (panel-owned lifecycle) and the fresh mount greets a new one.
const panelKey = ref(0);

const logixTurnContext = computed(() => ({
	element_name: elementLabel.value || "",
	current_script: localCurrentScript.value || props.currentScript || "",
	process_context: null,
}));

async function onLogixCardAction({ name, action, value, payload }) {
	if (name === "onefm.test_cases" && action === "run-test") {
		await runTestCase(payload);
		return;
	}
	if (name !== "onefm.script_diff" || action !== "apply-script") return;
	const code = value.modified_script || "";
	if (!code) return;
	const linked = localCurrentScript.value || props.currentScript || "";
	if (value.mode === "MODIFY" && linked) {
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.server_script_api.update_server_script",
				params: { script_name: linked, script: code },
			});
			if (props.eventBus) {
				props.eventBus.fire("spiff.script.update", {
					element: props.element, scriptType: props.scriptType, script: linked,
				});
			}
		} catch (e) {
			applyError.value = e?.message || String(e);
		}
		return;
	}
	// CREATE (or MODIFY with nothing linked): the naming dialog is the
	// apply target — same endpoint, same permission checks as before.
	applyScriptCode.value = code;
	applyScriptName.value = value.suggested_name || "";
	showApplyDialog.value = true;
}

// The TestCaseCard renders and requests; the host runs — it owns the
// linked-script name, so the endpoint call lives here, not in the card.
async function runTestCase(payload) {
	const report = payload && typeof payload.onResult === "function" ? payload.onResult : () => {};
	const linked = localCurrentScript.value || props.currentScript || "";
	if (!linked) {
		report({ passed: false, summary: "Create and link the script first — there is nothing to run yet." });
		return;
	}
	try {
		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.run_logix_test_case",
			method: "POST",
			params: {
				script_name: linked,
				inputs: JSON.stringify(payload.inputs || {}),
			},
		});
		report({
			passed: result?.passed ?? false,
			summary: result?.summary || (result?.passed ? "Test passed." : "Test failed."),
		});
	} catch (err) {
		report({ passed: false, summary: "Could not run the test — network error." });
	}
}

const showApplyDialog = ref(false);
const applyScriptName = ref("");
const applyScriptCode = ref("");
const applyError      = ref("");
const applyLoading    = ref(false);
const applyNameInput  = ref(null);

const localCurrentScript = ref("");

// ── Computed helpers ──────────────────────────────────────────────────
const elementLabel = computed(() => {
	if (!props.element) return "";
	const bo = props.element.businessObject;
	return bo?.name || props.element.id || "";
});

// ── Lifecycle ─────────────────────────────────────────────────────────
// A different BPMN element while the modal is open means a different
// subject — start a fresh conversation for it.
watch(
	() => props.element?.id,
	(newId, oldId) => {
		if (newId && oldId && newId !== oldId) {
			localCurrentScript.value = "";
			panelKey.value++;
		}
	},
);

async function applyScript() {
	const name = applyScriptName.value.trim();
	if (!name) return;

	applyError.value   = "";
	applyLoading.value = true;

	try {
		const data = await frappeRequest({
			url: "/api/method/one_bpmn.api.server_script_api.create_server_script",
			params: { script_name: name, script_type: "API", script: applyScriptCode.value },
		});
		const scriptName = data?.name || name;

		if (props.eventBus) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     scriptName,
			});
		}

		localCurrentScript.value = scriptName;
		showApplyDialog.value    = false;
		setTimeout(() => handleClose(), 1400);
	} catch (err) {
		applyError.value = err.message || "Failed to create script. Please try again.";
	} finally {
		applyLoading.value = false;
	}
}

// ── Reset / close ─────────────────────────────────────────────────────
// Conversation teardown is panel-owned: unmounting the AgentChatPanel ends
// the active Chat Conversation on the backend, so closing the modal (v-if)
// or remounting via panelKey covers both paths.
function resetConversation() {
	localCurrentScript.value = "";
	panelKey.value++;
}

function handleClose() {
	emit("update:modelValue", false);
}
</script>

<style scoped>
/* ── Scrim ──────────────────────────────────────────────────────────── */
.lx-scrim {
	position: fixed;
	inset: 0;
	background: rgba(0, 0, 0, 0.45);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 9999;
	backdrop-filter: blur(2px);
}

/* ── Chat window ────────────────────────────────────────────────────── */
.lx-window {
	display: flex;
	flex-direction: column;
	width: min(780px, 92vw);
	height: min(680px, 90vh);
	background: #fff;
	border-radius: 12px;
	box-shadow: 0 8px 32px rgba(0,0,0,.18), 0 2px 8px rgba(0,0,0,.10);
	overflow: hidden;
	font-family: "Google Sans", Roboto, "Segoe UI", system-ui, sans-serif;
}

/* ── Header ─────────────────────────────────────────────────────────── */
.lx-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 16px;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	flex-shrink: 0;
}

.lx-header-left {
	display: flex;
	align-items: center;
	gap: 10px;
	min-width: 0;
}

.lx-logo-icon {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 30px;
	height: 30px;
	border-radius: 50%;
	background: rgba(255,255,255,0.2);
	flex-shrink: 0;
	color: #fff;
}

.lx-logo-icon svg {
	width: 16px;
	height: 16px;
}

.lx-title {
	font-size: 16px;
	font-weight: 600;
	color: #fff;
	letter-spacing: .1px;
	flex-shrink: 0;
}

.lx-context-chip {
	background: rgba(255,255,255,0.2);
	border: 1px solid rgba(255,255,255,0.3);
	border-radius: 6px;
	padding: 2px 10px;
	font-size: 12px;
	font-weight: 500;
	color: rgba(255,255,255,0.9);
	max-width: 200px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.lx-header-actions {
	display: flex;
	align-items: center;
	gap: 4px;
}

.lx-icon-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 32px;
	height: 32px;
	border: none;
	border-radius: 50%;
	background: rgba(255,255,255,0.15);
	color: #fff;
	cursor: pointer;
	transition: background 0.18s;
	flex-shrink: 0;
}

.lx-icon-btn:hover { background: rgba(255,255,255,0.28); }
.lx-icon-btn svg { display: block; }


/* ── Apply dialog ───────────────────────────────────────────────────── */
.lx-apply-scrim { z-index: 10000; }

.lx-apply-window {
	background: #fff;
	border-radius: 12px;
	width: min(440px, 90vw);
	overflow: hidden;
	box-shadow: 0 8px 32px rgba(0,0,0,.18);
	font-family: "Google Sans", Roboto, system-ui, sans-serif;
}

.lx-apply-header { padding: 20px 24px 0; }
.lx-apply-title { font-size: 17px; font-weight: 600; color: #1c1b1f; }

.lx-apply-body {
	padding: 14px 24px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.lx-apply-hint { margin: 0; font-size: 14px; color: #555; line-height: 1.5; }
.lx-apply-field { display: flex; flex-direction: column; gap: 6px; }
.lx-apply-label { font-size: 12px; font-weight: 600; color: #555; }
.lx-required { color: #c00; }

.lx-apply-input {
	border: 1px solid #ccc;
	border-radius: 6px;
	padding: 8px 12px;
	font-size: 14px;
	font-family: inherit;
	outline: none;
	background: #fff;
	color: #1c1b1f;
	transition: border-color 0.15s;
}

.lx-apply-input:focus {
	border-color: #6c3fe0;
	box-shadow: 0 0 0 2px rgba(108,63,224,.15);
}

.lx-apply-error {
	font-size: 12px;
	color: #c00;
	background: #fff5f5;
	border-radius: 6px;
	padding: 8px 12px;
}

.lx-apply-actions {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	padding: 10px 24px 18px;
}

.lx-btn-text {
	border: none;
	background: transparent;
	color: #6c3fe0;
	font-size: 14px;
	font-weight: 500;
	font-family: inherit;
	padding: 8px 16px;
	border-radius: 6px;
	cursor: pointer;
	transition: background 0.15s;
}

.lx-btn-text:hover { background: rgba(108,63,224,.08); }

.lx-btn-filled {
	display: flex;
	align-items: center;
	gap: 6px;
	border: none;
	background: linear-gradient(135deg, #6c3fe0 0%, #9b59b6 100%);
	color: #fff;
	font-size: 14px;
	font-weight: 500;
	font-family: inherit;
	padding: 8px 20px;
	border-radius: 6px;
	cursor: pointer;
	transition: opacity 0.15s;
}

.lx-btn-filled:hover:not(:disabled) { opacity: 0.88; }
.lx-btn-filled:disabled { background: #ccc; cursor: not-allowed; }

/* ── Spinner ────────────────────────────────────────────────────────── */
.lx-spinner {
	width: 13px;
	height: 13px;
	border: 2px solid rgba(255,255,255,.4);
	border-top-color: #fff;
	border-radius: 50%;
	animation: lx-spin 0.7s linear infinite;
	display: inline-block;
}

@keyframes lx-spin { to { transform: rotate(360deg); } }

.lx-sdiff-empty { background: rgba(255,255,255,0.02); }
</style>
