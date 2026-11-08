import { toRaw } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigSave(ac) {
	const {
		props,
		emit,
		form,
		staticContextLoaded,
		configOwnedLimits,
		isSelector,
		rawElement,
		showNotice,
		serverMessage,
	} = ac;

	// on Save, write agent-level edits back to the linked
	// AI Agent Configuration.
	// Failure never blocks the shape save; the user is warned instead. A Live
	// agent is automatically re-provisioned by the backend so its chat map picks
	// up the change — silently: re-validation failures surface in deploy checks,
	// not as a popup on every save.
	async function writeBackToConfig() {
		if (!form.value.aiAgentConfig) return;
		// the MODEL is the agent's editable pick and writes back;
		// aiProvider is no longer sent — the provider is derived from the model.
		const fields = {
			aiModel: form.value.aiModel,
			aiSystemPrompt: form.value.aiSystemPrompt,
			aiMaxTokens: form.value.aiMaxTokens,
		};
		fields.aiTemperature = form.value.aiTemperature;
		for (const attr of configOwnedLimits.value) fields[attr] = form.value[attr];
		// Only once the agent was read, so the form's defaults never overwrite its real values.
		if (staticContextLoaded.value) {
			fields.aiToolChoice = form.value.aiToolChoice || "";
			fields.aiParallelToolCalls = form.value.aiParallelToolCalls ? 1 : 0;
			fields.aiThinkingBudgetTokens = form.value.aiThinkingBudgetTokens || 0;
			fields.aiTerminalTools = form.value.aiTerminalTools || "";
			fields.aiSandboxUseJob = form.value.aiSandboxUseJob ? 1 : 0;
			fields.aiSandboxRetryOnTestFailure = form.value.aiSandboxRetryOnTestFailure ? 1 : 0;
			fields.aiRequireReproduction = form.value.aiRequireReproduction ? 1 : 0;
		}
		// Screening is NOT sent here. It has its own writer (saveScreening, below),
		// and sending it from both places meant the resolver write landed second and
		// put the stale form value back — silently undoing whatever the user had just
		// picked in the Screening section. The editable copy lives on
		// screeningControls, not on form, so this endpoint has nothing current to say
		// about it. Creation is different and still goes through the resolver: the
		// agent has no record to read controls off yet.
		// memory is agent-level now, so it persists here rather than onto
		// the BPMN XML. The selector dialog has no memory section — sending its form
		// defaults would clobber the agent's real settings.
		if (!isSelector.value) {
			fields.aiConversationStore = form.value.aiConversationStore;
			fields.aiContextMaxMessages = form.value.aiContextMaxMessages;
			fields.aiLongTermMemory = form.value.aiLongTermMemory ? "Enabled" : "Disabled";
			fields.aiMemoryScope = form.value.aiLongTermMemory ? form.value.aiMemoryScope : "";
			fields.aiMemoryWriteMode = form.value.aiLongTermMemory
				? form.value.aiMemoryWriteMode
				: "";
			// Recall runs whenever memory is on, independent of write mode — sent
			// unconditionally (like aiCompactionKeepTail below), never zeroed when
			// memory is off, since a stray 0 would just fall back to the default.
			fields.aiMemoryTokenBudget = form.value.aiMemoryTokenBudget || 800;
			fields.aiMemoryDistillModel = form.value.aiMemoryDistillModel || "";
			fields.aiMemoryReconcileModel = form.value.aiMemoryReconcileModel || "";
			// Compaction. The thresholds are only meaningful while it is enabled, so
			// they are zeroed when it is off rather than left to fire on a re-enable
			// with settings the user has since forgotten about.
			fields.aiContextTokenBudget = form.value.aiContextTokenBudget || 0;
			fields.aiCompactionEnabled = form.value.aiCompactionEnabled ? 1 : 0;
			fields.aiCompactionKeepTail = form.value.aiCompactionKeepTail || 10;
			fields.aiGoldenDatasetMinimum = form.value.aiGoldenDatasetMinimum || 0;
			fields.aiGoldenDatasetTarget = form.value.aiGoldenDatasetTarget || 0;
			fields.aiRunTokenBudget = form.value.aiRunTokenBudget || 0;
			fields.aiRunCostBudget = form.value.aiRunCostBudget || 0;
			fields.aiCompactionModel = form.value.aiCompactionEnabled
				? form.value.aiCompactionModel || ""
				: "";
			fields.aiCompactionTokenThreshold = form.value.aiCompactionEnabled
				? form.value.aiCompactionTokenThreshold || 0
				: 0;
			fields.aiCompactionIdleMinutes = form.value.aiCompactionEnabled
				? form.value.aiCompactionIdleMinutes || 0
				: 0;
			fields.aiCompactionOnTaskBoundary =
				form.value.aiCompactionEnabled && form.value.aiCompactionOnTaskBoundary ? 1 : 0;
			fields.aiLoopCompactionThreshold = form.value.aiLoopCompactionThreshold || 0;
			fields.aiLoopCompactionKeepTurns = form.value.aiLoopCompactionKeepTurns || 8;
		}
		// examples and guard rails are agent-level, so they persist here
		// rather than onto the BPMN XML. Sent whole (the backend replaces the tables)
		// and only when they were read first — omitting the keys means "leave them".
		if (staticContextLoaded.value) {
			fields.aiSkills = form.value.aiSkills;
			fields.aiExamples = form.value.aiExamples;
			fields.aiGuardrails = form.value.aiGuardrails;
			// Blank rows are the ones the user added and never picked a role for.
			fields.aiAgentRoles = form.value.aiAgentRoles.filter((r) => r && r.role);
		}
		// Screening goes through security_api, which accepts ONLY screening fields —
		// keeping this endpoint from becoming a general writer for the whole agent.
		await ac.saveScreening();
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
					"\n\nUpdate the AI Agent Configuration record directly if the change should apply to the agent.",
			);
		}
	}

	async function save() {
		// every AI shape must be backed by an AI Agent Configuration —
		// raw provider setup is retired (the compile gate enforces the same rule).
		if (!form.value.aiAgentConfig) {
			showNotice(
				"Link an AI Agent Configuration",
				"Link an AI Agent Configuration before saving.\n" +
					"Pick an existing agent, use “+ Create new…”, or ask the assistant to " +
					"create one — setting up an AI task with a raw provider has been retired.",
			);
			return;
		}

		// the model comes from the linked agent's catalog pick. An
		// empty model here means the agent has none yet — fix it on the agent.
		if (!form.value.aiModel || !form.value.aiModel.trim()) {
			showNotice(
				"No model set",
				"No model is set. Pick an AI Model on the linked AI Agent Configuration " +
					"(or ask the assistant to change the model) — the provider follows from it.",
			);
			return;
		}

		// Validate JSON schema if provided
		if (
			!isSelector.value &&
			form.value.aiResponseFormat === "json" &&
			form.value.aiResponseSchema
		) {
			try {
				JSON.parse(form.value.aiResponseSchema);
			} catch (e) {
				showNotice(
					"Invalid Response Schema",
					"Response Schema is not valid JSON: " + e.message,
				);
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
				"spiffworkflow:aiTemperature": String(form.value.aiTemperature),
				"spiffworkflow:aiTopP": String(form.value.aiTopP),
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
			// memory settings are NOT written here any more — they live on
			// the linked AI Agent Configuration (see writeBackToConfig). Existing
			// diagrams keep their aiMemory* / aiConversationStore attributes untouched;
			// dispatch reads the agent first and only falls through to them when the
			// agent leaves a field blank.
		};

		modeling.updateModdleProperties(element, bo, patch);
		await writeBackToConfig();
		emit("close");
	}

	Object.assign(ac, { writeBackToConfig, save });
}
