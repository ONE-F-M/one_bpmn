/**
 * useEmailNotificationOptions: the lists the Email Notification editor picks from.
 */
import { createResource } from "frappe-ui";
import { ref } from "vue"

const FIELDS_URL = "processa.api.lookups.get_doctype_fields"

async function names(doctype) {
	const rows = await createResource({ url: "frappe.client.get_list", params: { doctype: doctype, fields: '["name"]', limit_page_length: 0, order_by: "name asc" } }).fetch()
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
			createResource({ url: "processa.api.lookups.get_recipient_docfields", method: "GET", params: { doctype } }).fetch(),
			createResource({ url: FIELDS_URL, method: "GET", params: { doctype, fieldtype_in: '["Table MultiSelect","Table"]', include_options: true } }).fetch(),
		])
		docFields.value = Array.isArray(fields) ? fields : []
		tableFields.value = Array.isArray(tables) ? tables : []
	}

	// the table's child DocType fields that link to User
	async function loadRowUserFields(childDoctype) {
		rowUserFields.value = []
		if (!childDoctype) return
		const fields = await createResource({ url: FIELDS_URL, method: "GET", params: { doctype: childDoctype, fieldtype_in: '["Link"]', include_options: true } }).fetch()
		rowUserFields.value = (Array.isArray(fields) ? fields : []).filter((f) => f.options === "User")
	}

	return { accounts, doctypes, roles, docFields, tableFields, rowUserFields, loading, loadLists, loadDoctypeFields, loadRowUserFields }
}
