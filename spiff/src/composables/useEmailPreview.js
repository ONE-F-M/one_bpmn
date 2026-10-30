import { ref, watch } from "vue"
import { frappePost } from "@/bpmn/shared/frappeResource"

const PREVIEW_DELAY_MS = 1000

// Server-rendered HTML version of the draft email, refreshed once the draft stops changing.
// request() gives the element type, DocType and settings to preview; by default the Email Notification draft.
export function useEmailPreview({ values, open, processModel, request = () => emailNotificationRequest(values) }) {
	const preview = ref({ html: "", message: "", error: "", docname: "" })
	const loading = ref(false)
	let timer = null
	let latest = 0

	async function refresh() {
		const call = ++latest
		loading.value = true
		try {
			const result = await frappePost("/api/method/one_bpmn.api.notification_api.preview_notification", {
				process_model: processModel.value,
				...request(),
			})
			if (call === latest) preview.value = { html: "", message: "", error: "", docname: "", ...result }
		} catch (e) {
			if (call === latest) preview.value = { html: "", message: "", error: e.message || String(e), docname: "" }
		} finally {
			if (call === latest) loading.value = false
		}
	}

	watch(
		[() => JSON.stringify(request()), open],
		([, isOpen]) => {
			clearTimeout(timer)
			if (isOpen) timer = setTimeout(refresh, PREVIEW_DELAY_MS)
		},
		{ immediate: true }
	)

	return { preview, loading }
}

function emailNotificationRequest(values) {
	return {
		element_type: "send_email",
		doctype: values.emailUseDoctype === "true" ? values.emailDoctype : "",
		settings: JSON.stringify(values),
	}
}
