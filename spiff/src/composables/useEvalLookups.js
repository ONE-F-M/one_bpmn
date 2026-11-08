import { ref } from "vue";
import { frappeRequest } from "frappe-ui";

const NO_SKILL = { label: "", value: "" };

async function listNames(doctype, fields) {
	return frappeRequest({
		url: "/api/method/frappe.client.get_list",
		method: "GET",
		params: { doctype, fields: JSON.stringify(fields), limit_page_length: 0 },
	});
}

export function useEvalLookups() {
	const providerOptions = ref([]);
	const aiModelOptions = ref([]);
	const skillOptions = ref([NO_SKILL]);

	async function fetchProviders() {
		try {
			const res = await listNames("AI Provider", ["name"]);
			providerOptions.value = (res || []).map((p) => ({ label: p.name, value: p.name }));
		} catch {
			providerOptions.value = [];
		}
	}

	async function fetchAiModels() {
		try {
			const res = await listNames("AI Model", ["name", "model_name"]);
			aiModelOptions.value = (res || []).map((m) => ({
				label: m.model_name || m.name,
				value: m.name,
			}));
		} catch {
			aiModelOptions.value = [];
		}
	}

	async function loadSkills() {
		try {
			const res = await listNames("AI Skill", ["name"]);
			skillOptions.value = [NO_SKILL].concat(
				(res || []).map((sk) => ({ label: sk.name, value: sk.name })),
			);
		} catch {
			skillOptions.value = [NO_SKILL];
		}
	}

	return {
		providerOptions,
		aiModelOptions,
		skillOptions,
		fetchProviders,
		fetchAiModels,
		loadSkills,
	};
}
