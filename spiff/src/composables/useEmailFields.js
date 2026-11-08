/**
 * useEmailFields: fields an email can show (own and linked) with their Arabic candidates.
 */
import { ref } from "vue"
import { frappeGet } from "@/bpmn/shared/frappeResource"
import { flattenEmailFields } from "@/bpmn/shared/notifyFields"

export function useEmailFields(fieldtypes) {
	const fields = ref([])
	const loading = ref(false)

	async function load(doctype) {
		fields.value = []
		if (!doctype) return
		loading.value = true
		try {
			const data = await frappeGet("/api/method/one_bpmn.api.utils.get_email_fields", { doctype })
			fields.value = flattenEmailFields(data, fieldtypes)
		} finally {
			loading.value = false
		}
	}

	return { fields, loading, load }
}
