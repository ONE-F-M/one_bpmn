import { createResource } from "frappe-ui";

export const processaSettings = createResource({
	url: "frappe.client.get",
	params: { doctype: "Processa Settings", name: "Processa Settings" },
});

let loading = null;

export function loadProcessaSettings() {
	loading ||= processaSettings.fetch().catch((error) => {
		loading = null;
		throw error;
	});
	return loading;
}
