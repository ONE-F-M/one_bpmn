import { ref } from "vue"
import { frappeRequest } from "frappe-ui"
import { downloadBlob } from "@/utils/downloadBpmn"

const API = "one_bpmn.api.insights_api"

// Loads the allocation report; a response to any request but the latest is dropped.
export function useCostAllocation() {
	const report = ref({})
	const loading = ref(true)
	const error = ref(null)
	const exporting = ref(false)
	let latest = 0

	async function load(params) {
		const seq = ++latest
		loading.value = true
		error.value = null
		try {
			const data = await frappeRequest({ url: `${API}.get_cost_allocation`, method: "POST", params })
			if (seq === latest) report.value = data
		} catch (e) {
			if (seq === latest) {
				report.value = {}
				error.value = e
			}
		} finally {
			if (seq === latest) loading.value = false
		}
		return seq === latest
	}

	async function exportFile(params) {
		exporting.value = true
		try {
			const { filename, content } = await frappeRequest({
				url: `${API}.export_cost_allocation`,
				method: "POST",
				params,
			})
			const bytes = Uint8Array.from(atob(content), (c) => c.charCodeAt(0))
			downloadBlob(new Blob([bytes]), filename)
		} finally {
			exporting.value = false
		}
	}

	return { report, loading, error, exporting, load, exportFile }
}
