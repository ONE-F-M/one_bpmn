/**
 * useDoctypeEmailThread: whether a DocType keeps an email thread
 * (email_append_to) and which field holds the sender's address.
 */
import { ref } from "vue"
import { frappeGet } from "@/bpmn/shared/frappeResource"

export function useDoctypeEmailThread() {
	const thread = ref({ email_append_to: false, sender_field: "" })
	const loading = ref(false)

	async function load(doctype) {
		thread.value = { email_append_to: false, sender_field: "" }
		if (!doctype) return
		loading.value = true
		try {
			thread.value = await frappeGet("/api/method/one_bpmn.api.utils.get_doctype_email_thread", { doctype })
		} finally {
			loading.value = false
		}
	}

	return { thread, loading, load }
}
