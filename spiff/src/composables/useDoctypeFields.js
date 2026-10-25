/**
 * useDoctypeFields: a DocType's fields of the given field types, for pickers.
 */
import { ref } from "vue"
import { frappeGet } from "@/bpmn/shared/frappeResource"

export function useDoctypeFields(fieldtypes) {
	const fields = ref([])
	const loading = ref(false)

	async function load(doctype) {
		fields.value = []
		if (!doctype) return
		loading.value = true
		try {
			const data = await frappeGet("/api/method/one_bpmn.api.utils.get_doctype_fields", {
				doctype,
				fieldtype_in: JSON.stringify(fieldtypes),
			})
			fields.value = Array.isArray(data) ? data : []
		} finally {
			loading.value = false
		}
	}

	return { fields, loading, load }
}
