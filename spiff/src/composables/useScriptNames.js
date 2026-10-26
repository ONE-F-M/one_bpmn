import { ref } from "vue"
import { frappeRequest } from "frappe-ui"

const names = ref([])
const error = ref("")
const loading = ref(false)
let fetchPromise = null

async function load() {
	loading.value = true
	try {
		const res = await frappeRequest({ url: "/api/method/one_bpmn.api.server_script_api.get_script_names" })
		names.value = res.message || res || []
	} catch (e) {
		error.value = e?.messages?.[0] || e?.message || String(e)
		fetchPromise = null
	} finally {
		loading.value = false
	}
}

export function useScriptNames() {
	if (!fetchPromise) fetchPromise = load()
	return { names, error, loading }
}
