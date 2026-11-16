import { ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { serverMessage } from "@/utils/serverMessage"

// Operator controls on a process instance (processa.api.instances); `busy` names the action in flight.
export function useInstanceControl() {
	const busy = ref("")

	async function runControl(method, instanceName, reason = "") {
		busy.value = method
		try {
			return await frappeRequest({
				url: `/api/method/processa.api.instances.${method}`,
				method: "POST",
				params: { instance_name: instanceName, reason },
			})
		} catch (e) {
			throw new Error(serverMessage(e))
		} finally {
			busy.value = ""
		}
	}

	return { busy, runControl }
}
