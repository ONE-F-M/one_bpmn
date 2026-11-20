import { ref } from "vue";
import { frappeRequest } from "frappe-ui";

const LINT_URL = "/api/method/processa.api.script_approvals.lint_server_script";
const REQUEST_URL = "/api/method/processa.api.script_approvals.request_script_approval";

// The live lint of the open script on its script task, and the approval request raised from it.
export function useLogixScriptSecurity() {
	const lint = ref(null);
	const requesting = ref(false);
	const requestError = ref("");

	async function runLint({ code, scriptName, processContext }) {
		if (!code.trim()) {
			lint.value = null;
			return;
		}
		try {
			lint.value = await frappeRequest({
				url: LINT_URL,
				method: "POST",
				params: {
					code,
					script_name: scriptName || "",
					process: processContext?.process || "",
					script_task: processContext?.element_id || "",
				},
			});
		} catch {
			lint.value = null;
		}
	}

	async function requestApproval({ scriptName, processContext, reason }) {
		requesting.value = true;
		requestError.value = "";
		try {
			return await frappeRequest({
				url: REQUEST_URL,
				method: "POST",
				params: {
					server_script: scriptName,
					process: processContext?.process || "",
					script_task: processContext?.element_id || "",
					script_task_label: processContext?.element_name || "",
					reason,
				},
			});
		} catch (error) {
			requestError.value =
				error?.messages?.[0] || error?.message || "The request could not be raised.";
			return null;
		} finally {
			requesting.value = false;
		}
	}

	return { lint, requesting, requestError, runLint, requestApproval };
}
