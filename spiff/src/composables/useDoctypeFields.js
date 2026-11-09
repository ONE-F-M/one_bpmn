/**
 * useDoctypeFields: a DocType's fields of the given field types, for pickers.
 */
import { createResource } from "frappe-ui";
import { ref } from "vue"

export function useDoctypeFields(fieldtypes) {
	const fields = ref([])
	const loading = ref(false)

	async function load(doctype) {
		fields.value = []
		if (!doctype) return
		loading.value = true
		try {
			const data = await createResource({ url: "one_bpmn.api.lookups.get_doctype_fields", method: "GET", params: {
				doctype,
				fieldtype_in: JSON.stringify(fieldtypes),
			} }).fetch()
			fields.value = Array.isArray(data) ? data : []
		} finally {
			loading.value = false
		}
	}

	return { fields, loading, load }
}
