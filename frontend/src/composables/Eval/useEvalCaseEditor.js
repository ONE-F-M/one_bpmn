import { computed, reactive, ref } from "vue";
import { frappeRequest } from "frappe-ui";
import {
	blankCaseForm,
	caseFormFromServer,
	caseFormPayload,
	caseSaveMessage,
	caseSources as sourcesOf,
	incompleteAssertionIndex,
	inputContextError as validateInputContext,
	newAssertion,
	newExpectedCall,
} from "@/utils/evalCaseForm";

export function useEvalCaseEditor(ctx) {
	const { suiteName } = ctx;
	const showCaseEditor = ref(false);
	const caseMode = ref("new");
	const savingCase = ref(false);
	const caseError = ref("");
	const caseForm = reactive(blankCaseForm());
	const startsMidConversation = ref(false);

	const isMemoryCase = computed(() => caseForm.case_type === "Memory");
	// value is mandatory on the doctype; catching it here lets the button explain itself.
	const incompleteAssertion = computed(() => incompleteAssertionIndex(caseForm.assertions));
	const inputContextError = computed(() =>
		validateInputContext(caseForm, startsMidConversation.value),
	);
	const caseSources = computed(() => sourcesOf(caseForm));
	// The expected-calls grid is only worth showing when an assertion checks it.
	const wantsToolCalls = computed(() =>
		caseForm.assertions.some((a) => a.assertion_type === "tool_calls"),
	);

	function resetCaseForm() {
		Object.assign(caseForm, blankCaseForm());
		startsMidConversation.value = false;
	}

	function useLoadedPrompt(text) {
		caseForm.input_user_prompt = text;
		if (!caseForm.title) caseForm.title = text.slice(0, 120);
	}

	function addExpectedCall() {
		caseForm.expected_tool_calls.push(newExpectedCall(caseForm.expected_tool_calls));
	}

	function removeExpectedCall(i) {
		caseForm.expected_tool_calls.splice(i, 1);
	}

	function addAssertion() {
		caseForm.assertions.push(newAssertion());
	}

	function removeAssertion(i) {
		caseForm.assertions.splice(i, 1);
	}

	function openNewCase() {
		resetCaseForm();
		caseMode.value = "new";
		caseError.value = "";
		showCaseEditor.value = true;
	}

	async function openEditCase(c) {
		caseMode.value = "edit";
		resetCaseForm();
		caseError.value = "";
		showCaseEditor.value = true;
		try {
			const res = await frappeRequest({
				url: "/api/method/processa.api.evals.get_eval_case",
				method: "GET",
				params: { name: c.name },
			});
			Object.assign(caseForm, caseFormFromServer(res));
			startsMidConversation.value = Boolean(res.input_context) && res.case_type !== "Memory";
		} catch (e) {
			console.error("Failed to load case:", e);
		}
	}

	async function saveCase() {
		savingCase.value = true;
		caseError.value = "";
		try {
			if (inputContextError.value) {
				caseError.value = inputContextError.value;
				savingCase.value = false;
				return;
			}
			const payload = caseFormPayload(caseForm, startsMidConversation.value);
			if (caseMode.value === "edit") {
				await frappeRequest({
					url: "/api/method/processa.api.evals.update_eval_case",
					method: "POST",
					params: { name: caseForm.name, ...payload },
				});
			} else {
				await frappeRequest({
					url: "/api/method/processa.api.evals.create_eval_case",
					method: "POST",
					params: { suite: suiteName, ...payload },
				});
			}
			showCaseEditor.value = false;
			ctx.fetchDetail();
		} catch (e) {
			console.error("Save case failed:", e);
			caseError.value = caseSaveMessage(e) || "Could not save the case.";
		} finally {
			savingCase.value = false;
		}
	}

	return {
		showCaseEditor,
		caseMode,
		savingCase,
		caseError,
		caseForm,
		startsMidConversation,
		isMemoryCase,
		incompleteAssertion,
		inputContextError,
		caseSources,
		wantsToolCalls,
		useLoadedPrompt,
		addExpectedCall,
		removeExpectedCall,
		addAssertion,
		removeAssertion,
		openNewCase,
		openEditCase,
		saveCase,
	};
}
