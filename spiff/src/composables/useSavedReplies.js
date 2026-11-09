/**
 * useSavedReplies: Helpdesk HD Saved Reply records (name, title, message) for the
 * Conversation tab's picker.
 */
import { createResource } from "frappe-ui";
import { ref } from "vue"

export function useSavedReplies() {
	const replies = ref([])
	const loading = ref(false)

	async function load() {
		loading.value = true
		try {
			const data = await createResource({ url: "frappe.client.get_list", params: { doctype: "HD Saved Reply", fields: JSON.stringify(["name", "title", "message"]),
				limit_page_length: 0,
				order_by: "title asc",
			} }).fetch()
			replies.value = Array.isArray(data) ? data : []
		} finally {
			loading.value = false
		}
	}

	return { replies, loading, load }
}
