import { onMounted, toRaw } from "vue";
import { frappeRequest } from "frappe-ui";
import { frappeGet } from "@/bpmn/shared/frappeResource";

export function useAgentConfigLoad(ac) {
	const {
		props,
		availableSkills,
		providers,
		agentConfigs,
		catalogModels,
		siteDefaults,
		form,
		triggerDoctype,
		rawElement,
	} = ac;

	// ── Load providers + existing element config ────────────────────────────────
	onMounted(async () => {
		try {
			const skills = await frappeGet("/api/resource/AI Skill", {
				fields: JSON.stringify(["name"]),
				filters: JSON.stringify([["status", "in", ["Active", "Published"]]]),
				limit_page_length: 100,
			});
			availableSkills.value = skills || [];
		} catch (e) {
			console.error("Failed to load skills", e);
		}

		// The server answers which models are usable, because the API key is a Password and
		// cannot be read here. The provider list is derived from the catalogue.
		try {
			const rows = await frappeRequest({
				url: "/api/method/one_bpmn.agents.agent_config_resolver.model_catalogue",
				method: "POST",
			});
			catalogModels.value = Array.isArray(rows) ? rows : [];
			providers.value = Array.from(
				new Set(catalogModels.value.map((m) => m.provider).filter(Boolean)),
			).map((name) => ({ name, provider_name: name }));
		} catch {
			catalogModels.value = [];
			providers.value = [];
		}

		try {
			const settings = await frappeGet("/api/resource/Processa Settings/Processa Settings", {
				fields: JSON.stringify([
					"default_compaction_model",
					"default_memory_distill_model",
					"default_memory_reconcile_model",
				]),
			});
			siteDefaults.value = {
				compaction: settings?.default_compaction_model || "",
				distill: settings?.default_memory_distill_model || "",
				reconcile: settings?.default_memory_reconcile_model || "",
			};
		} catch {
			siteDefaults.value = { compaction: "", distill: "", reconcile: "" };
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
		} catch {
			agentConfigs.value = [];
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
			// same reasoning as the two below it — must exist on the form
			// object for the same wholesale-replace reason.
			aiMemoryTokenBudget: numOr("aiMemoryTokenBudget", 800, parseInt),
			// these two live on the agent, but seed them from the diagram so
			// a map whose agent has not been migrated still shows its real setting.
			// They must exist on the form object — the linked-agent load only overlays
			// keys already present, and this assignment replaces form.value wholesale.
			aiMemoryDistillModel: get("aiMemoryDistillModel") || "",
			aiMemoryReconcileModel: get("aiMemoryReconcileModel") || "",
			// Compaction is agent-owned like the two above, but the keys must exist
			// here: this assignment replaces form.value wholesale, and the overlay
			// below only fills keys that are already present.
			aiContextTokenBudget: numOr("aiContextTokenBudget", 0, parseInt),
			aiCompactionEnabled: get("aiCompactionEnabled") === "true",
			aiCompactionKeepTail: numOr("aiCompactionKeepTail", 10, parseInt),
			aiCompactionModel: get("aiCompactionModel") || "",
			aiCompactionTokenThreshold: numOr("aiCompactionTokenThreshold", 0, parseInt),
			aiGoldenDatasetMinimum: numOr("aiGoldenDatasetMinimum", 0, parseInt),
			aiGoldenDatasetTarget: numOr("aiGoldenDatasetTarget", 0, parseInt),
			aiRunTokenBudget: 0,
			aiRunCostBudget: 0,
			aiToolChoice: "",
			aiParallelToolCalls: true,
			aiThinkingBudgetTokens: 0,
			aiTerminalTools: "",
			aiSandboxUseJob: false,
			aiSandboxRetryOnTestFailure: true,
			aiRequireReproduction: false,
			aiCompactionIdleMinutes: numOr("aiCompactionIdleMinutes", 0, parseInt),
			aiCompactionOnTaskBoundary: get("aiCompactionOnTaskBoundary") === "true",
			aiLoopCompactionThreshold: 0,
			aiLoopCompactionKeepTurns: 8,
			// agent-owned, with no diagram fallback — this assignment
			// replaces form.value wholesale, so the keys must exist here or
			// loadLinkedAgent has nothing to fill and the template binds
			// to undefined.
			aiExamples: [],
			aiGuardrails: [],
			aiAgentRoles: [],
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
			} catch {
				/* best effort */
			}
		}

		// show the linked agent's lifecycle so "why can't I deploy"
		// is visible before the compile error says it.
		ac.refreshLinkedAgentStatus();

		// The linked agent is the source of truth for the prompt, model, sampling,
		// memory, compaction, examples, guard rails, skills and permissions — so its
		// values are what the panel opens showing. Anything blank on the agent falls
		// through to the shape's own copy, exactly as dispatch does.
		await ac.loadLinkedAgent();

		// A shape saved before the provider was pickable carries a model but no
		// provider; settle it from the model so the lists open already narrowed.
		if (!form.value.aiProvider) ac.onModelChange();
	});
}
