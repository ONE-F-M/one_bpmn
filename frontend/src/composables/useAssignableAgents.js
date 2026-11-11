import { frappeRequest } from "frappe-ui";

// Draft and Needs Attention agents are included: evaluating an agent is how it stops being a Draft.
export async function listAssignableAgents() {
	const res = await frappeRequest({
		url: "/api/method/one_bpmn.api.evals.list_assignable_agents",
		method: "GET",
		params: { include_all: 1 },
	});
	return res || [];
}
