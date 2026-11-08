import { computed, onUnmounted, toRaw } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigAssistant(ac) {
	const {
		props,
		agentConfigs,
		form,
		assistantConversation,
		chatPanel,
		triggerDoctype,
		rawElement,
		showNotice,
	} = ac;

	// the modal sends RAW grounding refs; the server-side context
	// builder (ai_assistant.build_assistant_turn_context) assembles the map's
	// dialog_context from them — schema/sample reads stay permission-checked
	// server-side. The builder branches on `mode` to ground a selector turn with the
	// selector's runtime
	// rules and the sub-process digest instead of the agent-creation capability.
	const assistantTurnContext = computed(() => ({
		assistant_dialog: {
			mode: props.mode === "selector" ? "selector" : "agent",
			linked_config: form.value.aiAgentConfig || "",
			// The EXACT open BPMN Process Model record name — the assistant needs it
			// verbatim for proposed_config.process_model (the human-facing process
			// title is a different string and fails the creation gate).
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
						},
			),
		},
	}));

	// Selector turns need the LIVE canvas, not the saved model: the designer is
	// usually mid-edit, and the digest names the very task ids the recommended
	// prompts must reference. Serializing XML is async, so it rides the panel's
	// per-turn contextProvider hook (the seam ProsAlly opened) rather
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
			// No digest this turn: the assistant works without it rather than not at all.
			console.warn("[AI assistant] could not serialize diagram:", e);
		}
		return { assistant_dialog: dialog };
	}

	// cards render and request — the HOST applies. The panel re-emits
	// card actions here; each maps onto the dialog's own handlers and endpoints, so permission checks
	// and the creation process apply as usual.
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
			// A proposed update to an EXISTING config goes through the
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

	const NUMERIC_FIELDS = ["aiTemperature", "aiTopP", "aiMaxTokens", "aiTimeout", "aiMaxRetries"];

	// Apply one recommended value onto the open form. The card (or the tray's
	// per-field Apply) is the only caller; the shared cards track which suggestions
	// were applied.
	function applyRecommendation(key, value) {
		if (NUMERIC_FIELDS.includes(key)) {
			const n = Number(value);
			if (Number.isFinite(n)) form.value[key] = n;
		} else {
			form.value[key] = String(value);
		}
	}

	// The designer's confirm does not create anything itself: it relays the
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
		await ac.onAgentConfigSelect();
	}

	// confirm the assistant's update proposal — same
	// endpoint as the dialog's Save write-back: permission-checked,
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
				await ac.onAgentConfigSelect();
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

	Object.assign(ac, {
		assistantTurnContext,
		selectorTurnContext,
		onAssistantCardAction,
		endAssistantConversation,
		applyRecommendation,
		createProposedAgent,
		onAssistantAgentEvent,
		applyProposedUpdate,
	});
}
