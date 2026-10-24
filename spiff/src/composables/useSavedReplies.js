/**
 * useSavedReplies: Helpdesk HD Saved Reply records (name, title, message) for the
 * Conversation tab's picker.
 */
import { ref } from "vue"
import { frappeGet } from "@/bpmn/shared/frappeResource"

export function useSavedReplies() {
	const replies = ref([])
	const loading = ref(false)

	async function load() {
		loading.value = true
		try {
			const data = await frappeGet("/api/resource/HD Saved Reply", {
				fields: JSON.stringify(["name", "title", "message"]),
				limit_page_length: 0,
				order_by: "title asc",
			})
			replies.value = Array.isArray(data) ? data : []
		} finally {
			loading.value = false
		}
	}

	return { replies, loading, load }
}
