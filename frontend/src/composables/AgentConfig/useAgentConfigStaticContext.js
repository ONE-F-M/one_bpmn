import { computed } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigStaticContext(ac) {
	const { grantableRoles, rolesUnrestricted, agentUserEmail, form } = ac;

	function addSkill() {
		form.value.aiSkills.push({ skill: "", version_pin: "" });
	}

	function addAgentRole() {
		form.value.aiAgentRoles.push({ role: "" });
	}

	const agentUserLabel = computed(
		() => agentUserEmail.value || "its own user, created when the agent is first saved",
	);

	// What the picker offers: everything this user may grant, PLUS whatever the
	// agent already holds. The second half matters — an agent may legitimately hold
	// a role its editor cannot grant, and a <select> whose value is not among its
	// options renders BLANK. Without this, a role the agent really has looks like an
	// empty row, which reads as "no role" and invites someone to overwrite it.
	const roleOptions = computed(() => {
		const held = (form.value.aiAgentRoles || []).map((r) => r && r.role).filter(Boolean);
		return Array.from(new Set([...grantableRoles.value, ...held])).sort();
	});

	// The picker's options arrive on the same response as the rest of the agent, via
	// applyGrantableRoles below. An empty picker looks exactly like "you may grant
	// nothing", which is also a real answer the escalation guard gives.
	function applyGrantableRoles(fields) {
		grantableRoles.value = Array.isArray(fields?.aiGrantableRoles)
			? fields.aiGrantableRoles
			: [];
		rolesUnrestricted.value = !!fields?.aiRolesUnrestricted;
	}

	async function loadAgentUser(configName) {
		agentUserEmail.value = "";
		if (!configName) return;
		try {
			const res = await frappeRequest({
				url: "/api/method/frappe.client.get_value",
				method: "GET",
				params: {
					doctype: "AI Agent Configuration",
					filters: JSON.stringify({ name: configName }),
					fieldname: JSON.stringify(["agent_user"]),
				},
			});
			agentUserEmail.value = res?.agent_user || "";
		} catch {
			agentUserEmail.value = "";
		}
	}

	function addExample() {
		form.value.aiExamples.push({
			input: "",
			context_summary: "",
			trajectory: null,
			expected_output: "",
			note: "",
			enabled: 1,
		});
	}

	function addGuardrail() {
		form.value.aiGuardrails.push({ guardrail: "", category: "Other", enabled: 1 });
	}

	Object.assign(ac, {
		addSkill,
		addAgentRole,
		agentUserLabel,
		roleOptions,
		applyGrantableRoles,
		loadAgentUser,
		addExample,
		addGuardrail,
	});
}
