import { ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { serverMessage } from "@/utils/serverMessage"

// Operator controls on a process instance (one_bpmn.api.instance_control); `busy` names the action in flight.
export function useInstanceControl() {
	const busy = ref("")

	async function runControl(method, instanceName, reason = "") {
		busy.value = method
		try {
			return await frappeRequest({
				url: `/api/method/one_bpmn.api.instance_control.${method}`,
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
