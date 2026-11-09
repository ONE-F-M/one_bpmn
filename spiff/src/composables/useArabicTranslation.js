import { createResource } from "frappe-ui";
import { ref } from "vue"
import { createArabicTranslator } from "@/utils/arabicTranslation"

// Fills Arabic from English after a pause; edited is the editor's list of hand-edited fields.
export function useArabicTranslation({ edited = ref([]), processModel = ref("") } = {}) {
	const errors = ref({})
	const translator = createArabicTranslator({
		request: (text) =>
			createResource({ url: "one_bpmn.api.translation.translate", params: { text, process_model: processModel.value } }).fetch(),
		edited,
		errors,
	})
	return { ...translator, edited, errors }
}
