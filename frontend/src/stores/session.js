import { createResource } from "frappe-ui";

export const sessionRoles = createResource({ url: "frappe.core.doctype.user.user.get_roles" });

let loading = null;

export const sessionUser = () => window.frappe?.boot?.session_user || "";

export function loadSessionRoles() {
	loading ||= sessionRoles.fetch({ uid: sessionUser() }).catch((error) => {
		loading = null;
		throw error;
	});
	return loading;
}
