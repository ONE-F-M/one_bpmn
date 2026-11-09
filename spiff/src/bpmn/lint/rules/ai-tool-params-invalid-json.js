/** Flags a tool shape whose aiToolParams is not a JSON Schema object the agent can pass to the model. */

import { attr, inReferencedToolBox, isExecutable, label } from "../aiShapes.js";

function isPlainObject(value) {
	return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function problemWith(raw) {
	let schema;
	try {
		schema = JSON.parse(raw);
	} catch (error) {
		return `is not valid JSON (${error.message})`;
	}
	if (!isPlainObject(schema)) {
		return "must be a JSON object";
	}
	const { properties, required } = schema;
	if (properties !== undefined && !isPlainObject(properties)) {
		return 'needs "properties" to be an object';
	}
	if (required !== undefined && !(Array.isArray(required) && required.every((name) => name in (properties || {})))) {
		return 'needs "required" to list only names defined in "properties"';
	}
	return "";
}

export default function () {
	function check(node, reporter) {
		const raw = attr(node, "aiToolParams");
		if (!raw || !inReferencedToolBox(node) || !isExecutable(node)) {
			return;
		}
		const problem = problemWith(raw);
		if (problem) {
			reporter.report(node.id, `Tool '${label(node)}': Tool Parameters ${problem}.`);
		}
	}

	return { check };
}
