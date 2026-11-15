import { ref } from "vue";
import { frappeRequest } from "frappe-ui";

// Form fields the server lets replace the shape's own values; the rest stay as saved.
const PREVIEW_FORM_KEYS = [
	"aiAgentConfig",
	"aiBackend",
	"aiProvider",
	"aiModel",
	"aiSystemPrompt",
	"aiUserPrompt",
	"aiTemperature",
	"aiTopP",
	"aiMaxTokens",
	"aiTimeout",
	"aiMaxRetries",
	"aiResponseFormat",
	"aiResponseSchema",
];

// Preview and dry run of the task as it stands in the editor, unsaved form edits included.
export function useAgentConfigPreview(ac) {
	const { props, form } = ac;

	const sampleVariables = ref("{}");
	const sampleMessage = ref("");
	const sampleResults = ref("{}");
	const preview = ref(null);
	const previewLoading = ref(false);
	const previewError = ref(null);
	const dryRun = ref(null);
	const dryRunLoading = ref(false);
	const dryRunError = ref(null);

	async function requestParams() {
		const { xml } = await props.modeler.saveXML({ format: false });
		const values = Object.fromEntries(PREVIEW_FORM_KEYS.map((key) => [key, form.value[key]]));
		return {
			model_name: props.modelName,
			bpmn_xml: xml,
			bpmn_id: props.element.id,
			form: JSON.stringify(values),
			sample_variables: sampleVariables.value || "{}",
			sample_message: sampleMessage.value,
		};
	}

	async function loadPreview() {
		previewLoading.value = true;
		previewError.value = null;
		try {
			preview.value = await frappeRequest({
				url: "processa.api.process_maps.preview_ai_task",
				method: "POST",
				params: await requestParams(),
			});
		} catch (err) {
			preview.value = null;
			previewError.value = err;
		} finally {
			previewLoading.value = false;
		}
	}

	async function runDryRun() {
		dryRunLoading.value = true;
		dryRunError.value = null;
		dryRun.value = null;
		try {
			dryRun.value = await frappeRequest({
				url: "processa.api.process_maps.dry_run_ai_task",
				method: "POST",
				params: { ...(await requestParams()), sample_results: sampleResults.value || "{}" },
			});
		} catch (err) {
			dryRunError.value = err;
		} finally {
			dryRunLoading.value = false;
		}
	}

	Object.assign(ac, {
		sampleVariables,
		sampleMessage,
		sampleResults,
		preview,
		previewLoading,
		previewError,
		loadPreview,
		dryRun,
		dryRunLoading,
		dryRunError,
		runDryRun,
	});
}
