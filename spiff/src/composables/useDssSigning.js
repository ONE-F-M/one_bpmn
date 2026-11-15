import { ref } from "vue"
import { frappeRequest } from "frappe-ui"

const POLL_MS = 5000

// Runs the DSS signing process for a task action; sign() resolves {ok, reason} when the run ends (ok when signed or exempt).
export function useDssSigning() {
	const signing = ref(false)

	async function sign(instanceName, taskId, action) {
		signing.value = true
		try {
			const started = await frappeRequest({
				url: "/api/method/one_bpmn.api.instance_api.start_dss_signing",
				method: "POST",
				params: { instance_name: instanceName, task_id: taskId, action },
			})
			while (true) {
				await new Promise((resolve) => setTimeout(resolve, POLL_MS))
				const status = await frappeRequest({
					url: "/api/method/one_bpmn.api.instance_api.get_dss_signing_status",
					params: { signing_instance: started.instance, action },
				})
				if (status.finished) return { ok: status.signed || status.exempt, reason: status.reason }
			}
		} finally {
			signing.value = false
		}
	}

	return { signing, sign }
}
