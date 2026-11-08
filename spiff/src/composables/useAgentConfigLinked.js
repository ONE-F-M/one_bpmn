import { computed } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigLinked(ac) {
	const {
		showCreateAgent,
		agentIdEdited,
		newAgent,
		emptyNewAgent,
		linkedAgentStatus,
		rerunning,
		form,
		staticContextLoaded,
		configOwnedLimits,
		showNotice,
		serverMessage,
	} = ac;

	const agentStatusClass = computed(() =>
		linkedAgentStatus.value === "Live"
			? "agent-status-live"
			: ["Needs Attention", "Retired"].includes(linkedAgentStatus.value)
				? "agent-status-bad"
				: "agent-status-pending",
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
		} catch {
			/* badge stays blank */
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
					"the status beside the agent updates on its own.",
			);
			for (let i = 0; i < 30; i++) {
				await new Promise((r) => setTimeout(r, 4000));
				const before = linkedAgentStatus.value;
				await refreshLinkedAgentStatus();
				if (linkedAgentStatus.value === "Live") break;
				if (
					before !== linkedAgentStatus.value &&
					linkedAgentStatus.value === "Needs Attention"
				)
					break;
			}
		} catch (e) {
			showNotice("Couldn't re-run the checks", serverMessage(e));
		} finally {
			rerunning.value = false;
			refreshLinkedAgentStatus();
		}
	}

	// Limits the linked agent's record already holds. Only these are written back, so a default on screen never lands on the record.
	const LIMIT_ATTRS = ["aiTimeout", "aiMaxRetries", "aiTopP"];

	// Overlay the linked agent's static-context tables onto the form. Called on
	// open and whenever the linked agent changes, so what is on screen is what the
	// agent will actually be primed with.
	// Everything the modal shows about a linked agent comes from here, whether the
	// panel just opened or the designer picked a different agent from the dropdown.
	//
	// One loader serves both paths, so a task whose agent is already linked opens with the
	// agent's real prompt, model, temperature and token cap rather than the diagram's copy.
	//
	// Applying every field is safe: config_field_map omits blank values, so an unset
	// field on the agent falls through to the shape's own copy — the same fallback
	// dispatch performs.
	async function applyLinkedAgentFields(fields) {
		if (!fields) return;
		applyConfigFields(fields);
		configOwnedLimits.value = LIMIT_ATTRS.filter((attr) => fields[attr] != null);
		form.value.aiExamples = Array.isArray(fields?.aiExamples) ? fields.aiExamples : [];
		form.value.aiSkills = Array.isArray(fields?.aiSkills) ? fields.aiSkills : [];
		form.value.aiGuardrails = Array.isArray(fields?.aiGuardrails) ? fields.aiGuardrails : [];
		form.value.aiAgentRoles = Array.isArray(fields?.aiAgentRoles) ? fields.aiAgentRoles : [];
		ac.applyGrantableRoles(fields);
		staticContextLoaded.value = true;
	}

	// One round trip loads the agent's memory, static context and the roles the picker offers.
	async function loadLinkedAgent() {
		staticContextLoaded.value = false;
		if (!form.value.aiAgentConfig) return;
		try {
			const fields = await frappeRequest({
				url: "/api/method/one_bpmn.agents.agent_config_resolver.get_agent_config_for_shape",
				method: "POST",
				params: { config_name: form.value.aiAgentConfig },
			});
			await applyLinkedAgentFields(fields);
		} catch {
			// Unreadable agent — the shape's own values stay on screen, which is also
			// what dispatch falls back to, and Save leaves the agent's tables alone.
			return;
		}
		await ac.loadAgentUser(form.value.aiAgentConfig);
		await ac.loadScreening();
	}

	// Pull the linked configuration's current values into the form (live
	// link). The resolver returns shape-attribute keys (aiSystemPrompt,
	// aiProvider, aiModel, aiTemperature, aiMaxTokens) that map directly onto our

	const BOOLEAN_FORM_KEYS = [
		"aiCompactionEnabled",
		"aiCompactionOnTaskBoundary",
		"aiParallelToolCalls",
		"aiSandboxUseJob",
		"aiSandboxRetryOnTestFailure",
		"aiRequireReproduction",
	];

	function configValueToForm(key, val) {
		if (BOOLEAN_FORM_KEYS.includes(key)) {
			return val === true || val === 1 || ["true", "1"].includes(String(val).toLowerCase());
		}
		if (key !== "aiLongTermMemory") return val;
		return (
			val === true ||
			val === 1 ||
			["enabled", "true", "1"].includes(String(val).toLowerCase())
		);
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
	async function onAgentConfigSelect() {
		const value = form.value.aiAgentConfig;
		if (value === "__create__") {
			// open the inline create panel instead of linking. A NEW
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
		// Same loader the panel opens with, so picking an agent and opening a task
		// already linked to it put identical values on screen.
		await loadLinkedAgent();
	}

	Object.assign(ac, {
		agentStatusClass,
		refreshLinkedAgentStatus,
		rerunChecks,
		applyLinkedAgentFields,
		loadLinkedAgent,
		configValueToForm,
		applyConfigFields,
		onAgentConfigSelect,
	});
}
