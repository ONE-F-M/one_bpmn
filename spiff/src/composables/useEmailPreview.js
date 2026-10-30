import { ref, watch } from "vue"
import { frappePost } from "@/bpmn/shared/frappeResource"

const PREVIEW_DELAY_MS = 1000

// Server-rendered HTML version of the draft email, refreshed once the draft stops changing.
export function useEmailPreview({ values, open, processModel }) {
	const preview = ref({ html: "", message: "", error: "", docname: "" })
	const loading = ref(false)
	let timer = null
	let latest = 0

	async function refresh() {
		const request = ++latest
		loading.value = true
		try {
			const result = await frappePost("/api/method/one_bpmn.api.notification_api.preview_notification", {
				process_model: processModel.value,
				element_type: "send_email",
				doctype: values.emailUseDoctype === "true" ? values.emailDoctype : "",
				settings: JSON.stringify(values),
			})
			if (request === latest) preview.value = { html: "", message: "", error: "", docname: "", ...result }
		} catch (e) {
			if (request === latest) preview.value = { html: "", message: "", error: e.message || String(e), docname: "" }
		} finally {
			if (request === latest) loading.value = false
		}
	}

	watch(
		[() => JSON.stringify(values), open],
		([, isOpen]) => {
			clearTimeout(timer)
			if (isOpen) timer = setTimeout(refresh, PREVIEW_DELAY_MS)
		},
		{ immediate: true }
	)

	return { preview, loading }
}
