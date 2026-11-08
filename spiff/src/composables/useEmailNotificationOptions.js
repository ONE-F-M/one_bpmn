/**
 * useEmailNotificationOptions: the lists the Email Notification editor picks from.
 */
import { ref } from "vue"
import { frappeGet } from "@/bpmn/shared/frappeResource"

const FIELDS_URL = "/api/method/one_bpmn.api.utils.get_doctype_fields"

async function names(doctype) {
	const rows = await frappeGet(`/api/resource/${doctype}`, { fields: '["name"]', limit_page_length: 0, order_by: "name asc" })
	return (Array.isArray(rows) ? rows : []).map((r) => r.name)
}

export function useEmailNotificationOptions() {
	const accounts = ref([])
	const doctypes = ref([])
	const roles = ref([])
	const docFields = ref([])
	const tableFields = ref([])
	const rowUserFields = ref([])
	const loading = ref(false)

	async function loadLists() {
		loading.value = true
		try {
			;[accounts.value, doctypes.value, roles.value] = await Promise.all(["Email Account", "DocType", "Role"].map(names))
		} finally {
			loading.value = false
		}
	}

	// recipient fields and table fields of the DocType the email is based on
	async function loadDoctypeFields(doctype) {
		docFields.value = []
		tableFields.value = []
		if (!doctype) return
		const [fields, tables] = await Promise.all([
			frappeGet("/api/method/one_bpmn.api.utils.get_recipient_docfields", { doctype }),
			frappeGet(FIELDS_URL, { doctype, fieldtype_in: '["Table MultiSelect","Table"]', include_options: true }),
		])
		docFields.value = Array.isArray(fields) ? fields : []
		tableFields.value = Array.isArray(tables) ? tables : []
	}

	// the table's child DocType fields that link to User
	async function loadRowUserFields(childDoctype) {
		rowUserFields.value = []
		if (!childDoctype) return
		const fields = await frappeGet(FIELDS_URL, { doctype: childDoctype, fieldtype_in: '["Link"]', include_options: true })
		rowUserFields.value = (Array.isArray(fields) ? fields : []).filter((f) => f.options === "User")
	}

	return { accounts, doctypes, roles, docFields, tableFields, rowUserFields, loading, loadLists, loadDoctypeFields, loadRowUserFields }
}
