import { ref } from "vue"
import { frappePost } from "@/bpmn/shared/frappeResource"
import { createArabicTranslator } from "@/utils/arabicTranslation"

// Fills Arabic from English after a pause; edited is the editor's list of hand-edited fields.
export function useArabicTranslation({ edited = ref([]), processModel = ref("") } = {}) {
	const errors = ref({})
	const translator = createArabicTranslator({
		request: (text) =>
			frappePost("/api/method/one_bpmn.utils.translation.translate", { text, process_model: processModel.value }),
		edited,
		errors,
	})
	return { ...translator, edited, errors }
}
