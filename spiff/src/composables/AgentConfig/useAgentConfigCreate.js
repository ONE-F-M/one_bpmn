import { computed } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigCreate(ac) {
	const {
		agentConfigs,
		showCreateAgent,
		creatingAgent,
		newAgent,
		form,
		showNotice,
		serverMessage,
	} = ac;

	const scrubbedAgentId = computed(() =>
		(newAgent.value.agent_name || "")
			.toLowerCase()
			.trim()
			.replace(/[^a-z0-9]+/g, "_")
			.replace(/^_+|_+$/g, ""),
	);

	// create the AI Agent Configuration from the dialog. The record is
	// inserted as Chat + Draft with the user's own permissions; the AI Agent
	// Creation Process starts on insert and takes it to Live. On success the new
	// agent is linked on this shape and its values pulled into the form.
	async function createAgent() {
		if (creatingAgent.value) return;
		if (!newAgent.value.agent_name.trim())
			return showNotice("Missing information", "Agent name is required.");
		if (!newAgent.value.chat_mode_label.trim())
			return showNotice("Missing information", "A chat mode label is required.");
		if (!newAgent.value.ai_model)
			return showNotice(
				"Missing information",
				"Pick an AI Model — the provider follows from it.",
			);
		creatingAgent.value = true;
		try {
			const payload = {
				...newAgent.value,
				agent_id: newAgent.value.agent_id.trim() || scrubbedAgentId.value,
				sample_prompts: newAgent.value.sample_prompts.filter((sp) =>
					(sp.prompt || "").trim(),
				),
				enabled_skills: newAgent.value.ai_skills.filter((sk) => (sk.skill || "").trim()),
			};
			const res = await frappeRequest({
				url: "/api/method/one_bpmn.ai_agent_registry.provisioning.agent_config_resolver.create_agent_configuration",
				method: "POST",
				params: { payload: JSON.stringify(payload) },
			});
			agentConfigs.value.push({ name: res.name, agent_id: res.agent_id });
			form.value.aiAgentConfig = res.name;
			await ac.onAgentConfigSelect();
			showCreateAgent.value = false;
			showNotice(
				"Agent created",
				`"${res.name}" created and linked to this task.\n` +
					(res.creation_instance
						? `The AI Agent Creation Process is running (instance ${res.creation_instance}) — it will take the agent to Live.`
						: "The creation process did not start (model inactive?) — check the AI Agent Configuration record."),
			);
		} catch (e) {
			showNotice("Could not create the agent configuration", serverMessage(e));
		} finally {
			creatingAgent.value = false;
		}
	}

	Object.assign(ac, { scrubbedAgentId, createAgent });
}
