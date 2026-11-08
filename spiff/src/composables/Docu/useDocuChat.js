import { computed } from "vue";
import { frappeRequest } from "frappe-ui";
import { serverMessage } from "@/utils/serverMessage.js";
import { DOCU_API } from "@/utils/docuApi";

export function useDocuChat({ props, dtName, dtModule, loadIr, autosave }) {
	const { saveNotes, childChanges, saveError, saveState } = autosave;

	const docuTurnContext = computed(() => ({
		doctype: dtName.value || props.doctype || "",
		target_module: dtModule.value || "",
		process_context: props.processContext || null,
	}));

	const hostContextLine = computed(() =>
		props.doctype
			? `Happy to help with changes to **${props.doctype}** doctype. How would you like me to assist in redefining it or its fields?`
			: "",
	);

	function onDocuCardAction({ name, action, value, fail }) {
		if (name === "onefm.doctype_schema" && action === "apply-schema" && value.doctype_ir) {
			loadIr(value.doctype_ir);
			loadChildChanges(value.doctype_ir);
		}
		if (name === "onefm.script_diff" && action === "apply-script")
			applyFormScript(value, fail);
	}

	async function applyFormScript({ apply_target: doctype, modified_script: script }, fail) {
		try {
			saveNotes.value = await frappeRequest({
				url: `${DOCU_API}apply_client_script`,
				method: "POST",
				params: { doctype, script },
			});
		} catch (e) {
			fail(serverMessage(e));
		}
	}

	async function loadChildChanges(ir) {
		childChanges.value = [];
		try {
			const res = await frappeRequest({
				url: `${DOCU_API}preview_doctype`,
				params: { ir: JSON.stringify(ir) },
			});
			childChanges.value = [
				...(res?.child_changes || []).map((c) => `${c.table}: ${c.lines.join(" ")}`),
				...(res?.warnings || []),
			];
		} catch (e) {
			saveError.value = serverMessage(e);
			saveState.value = "error";
		}
	}

	return { docuTurnContext, hostContextLine, onDocuCardAction };
}
