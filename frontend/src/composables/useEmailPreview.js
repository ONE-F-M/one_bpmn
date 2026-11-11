import { createResource } from "frappe-ui";
import { ref, watch } from "vue"

const PREVIEW_DELAY_MS = 1000

// Server-rendered HTML version of the draft email, refreshed once the draft stops changing.
// request() gives the element type, DocType and settings to preview; by default the Email Notification draft.
export function useEmailPreview({ values, open, processModel, request = () => emailNotificationRequest(values) }) {
	const preview = ref({ html: "", html_ar: "", sender: "", message: "", error: "", docname: "" })
	const loading = ref(false)
	let timer = null
	let latest = 0

	async function refresh() {
		const call = ++latest
		loading.value = true
		try {
			const result = await createResource({ url: "one_bpmn.api.notifications.preview_notification", params: {
				process_model: processModel.value,
				...request(),
			} }).fetch()
			if (call === latest) preview.value = { html: "", html_ar: "", sender: "", message: "", error: "", docname: "", ...result }
		} catch (e) {
			if (call === latest) preview.value = { html: "", html_ar: "", sender: "", message: "", error: e.message || String(e), docname: "" }
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
