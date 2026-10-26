import { ref } from "vue"
import { frappeRequest } from "frappe-ui"

const API = "/api/method/one_bpmn.api.eval_api."

// Real conversations with a suite's agent, for building a case's earlier conversation.
export function useCaseConversations(suite) {
	const conversations = ref([])
	const messages = ref([])
	const loading = ref(false)
	const error = ref("")

	async function call(method, params) {
		loading.value = true
		error.value = ""
		try {
			return await frappeRequest({ url: API + method, method: "GET", params: { suite, ...params } })
		} catch (e) {
			error.value = e?.message || "Could not load the conversation."
			return null
		} finally {
			loading.value = false
		}
	}

	async function search(term) {
		conversations.value = (await call("list_conversations_for_case", { search: term || "" })) || []
	}

	async function open(conversation) {
		messages.value = (await call("get_conversation_for_case", { conversation })) || []
	}

	function contextUpTo(conversation, message, includeMessage) {
		return call("conversation_context_for_case", { conversation, message, include_message: includeMessage ? 1 : 0 })
	}

	return { conversations, messages, loading, error, search, open, contextUpTo }
}
