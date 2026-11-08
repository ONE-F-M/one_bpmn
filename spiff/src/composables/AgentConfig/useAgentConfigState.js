import { computed, ref, toRaw } from "vue";

export const AGENT_CONFIG_KEY = Symbol("agentConfigModal");

export function createAgentConfigContext(props, emit) {
	const availableSkills = ref([]);

	// what this agent is permitted to do. The picker offers only what the
	// CURRENT user may grant, and the backend enforces the same list — an option that
	// cannot be saved should never be offered.
	const grantableRoles = ref([]);
	const rolesUnrestricted = ref(false);
	const agentUserEmail = ref("");

	// bpmn-js elements must never be touched as Vue reactive proxies — the renderer
	// reads non-configurable properties (e.g. labels) that a Proxy cannot return,
	// throwing on re-render. Always unwrap to the raw element before using it.
	function rawElement() {
		return toRaw(props.element);
	}

	const isSelector = computed(() => props.mode === "selector");

	const providers = ref([]);
	const agentConfigs = ref([]);
	const catalogModels = ref([]); // AI Model catalog
	// Site-wide model defaults from Processa Settings. A blank model picker means
	// "inherit"; the option names the site default so an unset field is not mistaken for
	// a broken one. Best-effort: a designer who cannot read Processa Settings still
	// gets the plain label.
	const siteDefaults = ref({ compaction: "", distill: "", reconcile: "" });

	// ── Create-new-agent panel state ──
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
		// chosen at creation rather than left to a later visit to the desk
		// form. Blank means "take the doctype default", so the panel never has to
		// restate what that default is.
		pii_screening: "",
		output_screening_mode: "",
	});
	const newAgent = ref(emptyNewAgent());

	// ── Linked agent lifecycle badge: deployment requires Live ──
	const linkedAgentStatus = ref("");

	const rerunning = ref(false);

	// ── Per-agent screening ─────────────────────────────────────────
	// The list comes from the server, which reads the doctype's real fields, so this
	// component never has to know which screening stories have shipped.
	const screeningControls = ref([]);

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
		// caps the injected recall block's estimated size. See the
		// field-hint in the template for why 0 isn't offered as "no cap" here.
		aiMemoryTokenBudget: 800,
		// blank means "inherit" — site default, then the agent's own model.
		aiMemoryDistillModel: "",
		aiMemoryReconcileModel: "",
		// Conversation compaction. Off by default: a site that has not asked for it
		// must see no change in what its agents send.
		aiContextTokenBudget: 0,
		aiCompactionEnabled: false,
		aiCompactionKeepTail: 10,
		aiCompactionModel: "",
		aiCompactionTokenThreshold: 0,
		aiCompactionIdleMinutes: 0,
		aiCompactionOnTaskBoundary: false,
		// Tool loop compaction is separate from conversation compaction; 0 is off.
		aiLoopCompactionThreshold: 0,
		aiLoopCompactionKeepTurns: 8,
		// The golden dataset bar. 0 is "no bar": the dataset shows a count and nothing to measure it against.
		aiGoldenDatasetMinimum: 0,
		aiGoldenDatasetTarget: 0,
		// Agent-owned: a run stops once it passes either budget; 0 is no budget.
		aiRunTokenBudget: 0,
		aiRunCostBudget: 0,
		aiToolChoice: "",
		aiParallelToolCalls: true,
		aiThinkingBudgetTokens: 0,
		aiTerminalTools: "",
		aiSandboxUseJob: false,
		aiSandboxRetryOnTestFailure: true,
		aiRequireReproduction: false,
		// the agent's frozen static context. Always arrays — they are
		// replaced wholesale by loadLinkedAgent once the agent is read.
		aiExamples: [],
		aiGuardrails: [],
		// the roles the agent's own user holds — what it is permitted to do.
		aiAgentRoles: [],
	});

	// True once the linked agent's examples/guard rails have actually been read.
	// Save only writes the two tables back when this is set: an unread agent leaves
	// the form arrays empty, and sending those would silently wipe its static
	// context.
	const staticContextLoaded = ref(false);

	const configOwnedLimits = ref([]);

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
	const assistantConversation = ref(""); // Chat Conversation driving the dialog
	const chatPanel = ref(null);

	// Grounding the designer never types: the DocType the process is triggered on.
	// The assistant looks schemas up with its own tools,
	// but a selector turn ships this one automatically, because its evidence
	// template is written in {{ doc.<field> }} terms and guessing them is exactly
	// what the digest cannot do for it.
	const triggerDoctype = ref("");

	return {
		props,
		emit,
		availableSkills,
		grantableRoles,
		rolesUnrestricted,
		agentUserEmail,
		providers,
		agentConfigs,
		catalogModels,
		siteDefaults,
		showCreateAgent,
		creatingAgent,
		agentIdEdited,
		newAgent,
		emptyNewAgent,
		linkedAgentStatus,
		rerunning,
		screeningControls,
		form,
		staticContextLoaded,
		configOwnedLimits,
		notice,
		assistantConversation,
		chatPanel,
		triggerDoctype,
		isSelector,
		rawElement,
		showNotice,
		serverMessage,
	};
}
