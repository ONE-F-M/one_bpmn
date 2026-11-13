/**
 * useEmailFields: fields an email can show (own and linked) with their Arabic candidates.
 */
import { createResource } from "frappe-ui";
import { ref } from "vue"
import { flattenEmailFields } from "@/bpmn/shared/notifyFields"

export function useEmailFields(fieldtypes) {
	const fields = ref([])
	const loading = ref(false)

	async function load(doctype) {
		fields.value = []
		if (!doctype) return
		loading.value = true
		try {
			const data = await createResource({ url: "processa.api.lookups.get_email_fields", method: "GET", params: { doctype } }).fetch()
			fields.value = flattenEmailFields(data, fieldtypes)
		} finally {
			loading.value = false
		}
	}

	return { fields, loading, load }
}
