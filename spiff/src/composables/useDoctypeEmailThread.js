/**
 * useDoctypeEmailThread: whether a DocType keeps an email thread
 * (email_append_to) and which field holds the sender's address.
 */
import { createResource } from "frappe-ui";
import { ref } from "vue"

export function useDoctypeEmailThread() {
	const thread = ref({ email_append_to: false, sender_field: "" })
	const loading = ref(false)

	async function load(doctype) {
		thread.value = { email_append_to: false, sender_field: "" }
		if (!doctype) return
		loading.value = true
		try {
			thread.value = await createResource({ url: "one_bpmn.api.lookups.get_doctype_email_thread", method: "GET", params: { doctype } }).fetch()
		} finally {
			loading.value = false
		}
	}

	return { thread, loading, load }
}
