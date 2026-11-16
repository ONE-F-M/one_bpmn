import { createResource } from "frappe-ui";

// Enabled roles for a picker, narrowed by the typed text.
export function fetchRoles(txt) {
	const filters = [["disabled", "=", 0]];
	if (txt) filters.push(["name", "like", `%${txt}%`]);
	return createResource({
		url: "frappe.client.get_list",
		params: {
			doctype: "Role",
			fields: '["name"]',
			filters: JSON.stringify(filters),
			limit_page_length: 50,
			order_by: "name asc",
		},
	}).fetch();
}
