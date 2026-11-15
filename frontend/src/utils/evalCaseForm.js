import { midConversationError } from "@/utils/evalContext";

export function blankCaseForm() {
	return {
		name: "",
		title: "",
		input_user_prompt: "",
		expected_output: "",
		assertions: [],
		case_type: "Output",
		target_skill: "",
		source_feedback: "",
		source_security_event: "",
		source_run: "",
		expected_tool_calls: [],
		input_context: "",
	};
}

export function caseFormFromServer(res) {
	return {
		name: res.name,
		title: res.title,
		input_user_prompt: res.input_user_prompt || "",
		expected_output: res.expected_output || "",
		case_type: res.case_type || "Output",
		target_skill: res.target_skill || "",
		source_feedback: res.source_feedback || "",
		source_security_event: res.source_security_event || "",
		source_run: res.source_run || "",
		input_context: res.input_context || "",
		assertions: (res.assertions || []).map((a) => ({
			assertion_type: a.assertion_type,
			value: a.value || "",
			judge_provider: a.judge_provider || "",
			judge_model: a.judge_model || "",
			pass_threshold: a.pass_threshold ?? 4,
		})),
		expected_tool_calls: (res.expected_tool_calls || []).map((e) => ({
			call_order: e.call_order || 1,
			tool_name: e.tool_name || "",
			argument: e.argument || "",
			matcher: e.matcher || "equals",
			expected_value: e.expected_value || "",
		})),
	};
}

export function newAssertion() {
	return {
		assertion_type: "contains",
		value: "",
		judge_provider: "",
		judge_model: "",
		pass_threshold: 4,
	};
}

export function newExpectedCall(calls) {
	const next = calls.length ? Math.max(...calls.map((e) => Number(e.call_order) || 0)) + 1 : 1;
	return {
		call_order: next,
		tool_name: "",
		argument: "",
		matcher: "equals",
		expected_value: "",
	};
}

// Index of the first assertion with no value, or -1.
export function incompleteAssertionIndex(assertions) {
	return assertions.findIndex((a) => !(a.value || "").trim());
}

export function inputContextError(form, startsMidConversation) {
	if (form.case_type !== "Memory")
		return startsMidConversation ? midConversationError(form.input_context) : "";
	const text = (form.input_context || "").trim();
	if (!text) return "Input Context is required for a Memory case.";
	try {
		const parsed = JSON.parse(text);
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
			return "Input Context must be a JSON object.";
		if (!parsed.scope_key)
			return "Input Context needs a scope_key: the agent element whose memories to measure.";
		return "";
	} catch {
		return "Input Context is not valid JSON.";
	}
}

export function caseFormPayload(form, startsMidConversation) {
	return {
		title: form.title,
		input_user_prompt: form.input_user_prompt,
		expected_output: form.expected_output,
		assertions: JSON.stringify(form.assertions),
		case_type: form.case_type,
		target_skill: form.target_skill,
		expected_tool_calls: JSON.stringify(form.expected_tool_calls),
		input_context:
			form.case_type === "Memory" || startsMidConversation ? form.input_context : "",
	};
}

export function caseSources(form) {
	const from = [];
	if (form.source_feedback) from.push({ label: `feedback ${form.source_feedback}` });
	if (form.source_security_event) {
		from.push({
			label: `security event ${form.source_security_event}`,
			to: `/processa/security?event=${encodeURIComponent(form.source_security_event)}`,
		});
	}
	if (form.source_run) {
		from.push({
			label: `run ${form.source_run}`,
			to: `/processa/runs/${encodeURIComponent(form.source_run)}`,
		});
	}
	return from;
}

// _server_messages is a JSON array of JSON strings; e.message is the bare exception class for a 417.
export function caseSaveMessage(e) {
	const raw = e?._server_messages || e?.exc || "";
	try {
		const parsed = JSON.parse(raw);
		const first = Array.isArray(parsed) ? parsed[0] : parsed;
		const inner = typeof first === "string" ? JSON.parse(first) : first;
		return (inner?.message || "").replace(/<[^>]*>/g, "").trim();
	} catch {
		return (e?.message || "").trim();
	}
}
