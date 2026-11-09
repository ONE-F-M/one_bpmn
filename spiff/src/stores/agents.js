import { createResource } from "frappe-ui";

export const agentConfigs = createResource({
	url: "frappe.client.get_list",
	params: {
		doctype: "AI Agent Configuration",
		fields: JSON.stringify(["name", "agent_id"]),
		filters: JSON.stringify([["enabled", "=", 1]]),
		limit_page_length: 100,
		order_by: "name asc",
	},
});

let loading = null;

export function loadAgentConfigs() {
	loading ||= agentConfigs.fetch().catch((error) => {
		loading = null;
		throw error;
	});
	return loading;
}
