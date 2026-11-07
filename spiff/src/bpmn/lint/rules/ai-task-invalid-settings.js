/** Flags an AI task carrying a raw API key, a bad Max Tokens, or a response schema that is not JSON. */

import { attr, isAiAgent, isAiSelector, isExecutable, label } from "../aiShapes.js";

const RAW_KEY = /^(sk-|key-)/i;
const RAW_KEY_ATTRIBUTES = ["spiffworkflow:aiApiKey", "spiffworkflow:aiKey"];

function carriesRawKey(node) {
	return Object.entries(node.$attrs || {}).some(
		([name, value]) =>
			RAW_KEY_ATTRIBUTES.includes(name) || (name.startsWith("spiffworkflow:ai") && RAW_KEY.test(String(value)))
	);
}

function isJson(text) {
	try {
		JSON.parse(text);
		return true;
	} catch {
		return false;
	}
}

function problemsWith(node) {
	const problems = [];
	if (carriesRawKey(node)) {
		problems.push("holds a raw API key. Use an AI Agent Configuration instead.");
	}
	const maxTokens = node.get("spiffworkflow:aiMaxTokens");
	if (maxTokens !== undefined && !(/^\d+$/.test(String(maxTokens).trim()) && Number(maxTokens) > 0)) {
		problems.push("needs Max Tokens to be a whole number above 0.");
	}
	const schema = attr(node, "aiResponseSchema");
	if (attr(node, "aiResponseFormat") === "json" && schema && !isJson(schema)) {
		problems.push("has a Response Schema that is not valid JSON.");
	}
	return problems;
}

export default function () {
	function check(node, reporter) {
		if (!(isAiAgent(node) || isAiSelector(node)) || !isExecutable(node)) {
			return;
		}
		for (const problem of problemsWith(node)) {
			reporter.report(node.id, `AI task "${label(node)}" ${problem}`);
		}
	}

	return { check };
}
