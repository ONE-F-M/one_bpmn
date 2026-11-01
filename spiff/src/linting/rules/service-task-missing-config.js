/** Flags a Service Task whose Service Type is missing a setting the engine needs, so it would do nothing when it runs. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

const has = (node, name) => Boolean(attr(node, name));
const hasAny = (node, names) => names.some((name) => has(node, name));

function parseJson(text) {
	try {
		return { value: JSON.parse(text) };
	} catch {
		return { error: true };
	}
}

function applyWorkflowProblems(node) {
	return hasAny(node, ["workflowState", "docStatus"]) ? [] : ["needs a Workflow State or a Document Status"];
}

function sendEmailProblems(node) {
	const recipients = ["emailTo", "emailToDocFields", "emailToTableField", "emailToRoles"];
	return hasAny(node, recipients) ? [] : ["has no recipients"];
}

function pushNotificationProblems(node) {
	return hasAny(node, ["pushToUsers", "pushToDocFields", "pushToRoles"]) ? [] : ["has no recipients"];
}

function updateFieldProblems(node) {
	const rows = attr(node, "updateFieldRows");
	if (!rows) {
		return has(node, "updateFieldName") ? [] : ["has no field to update"];
	}
	const { value, error } = parseJson(rows);
	if (error || !Array.isArray(value)) {
		return ["has Field Updates that are not a valid JSON list"];
	}
	return value.some((row) => String(row?.field || "").trim()) ? [] : ["has no field to update"];
}

const GCHAT_RECIPIENT_FIELD = { User: "gchatEmail", DocField: "gchatDocField", "Table Field": "gchatTableField" };

function googleChatProblems(node) {
	const problems = [];
	const type = attr(node, "gchatType");
	if (type !== "individual" && type !== "space") {
		return ["needs a destination type of individual or space"];
	}
	if (!has(node, "gchatMessage")) {
		problems.push("has no message");
	}
	if (type === "space") {
		if (!has(node, "gchatSpaceId")) {
			problems.push("has no space id");
		}
		return problems;
	}
	const basis = attr(node, "gchatRecipientBasis") || "User";
	const field = GCHAT_RECIPIENT_FIELD[basis];
	if (!field) {
		problems.push(`has an unknown recipient basis "${basis}"`);
	} else if (!has(node, field)) {
		problems.push("has no recipient");
	}
	return problems;
}

function connectorProblems(node) {
	const problems = ["connectorId", "operation"].filter((name) => !has(node, name)).map((name) => `has no ${name}`);
	const params = attr(node, "connectorParams");
	if (params) {
		const { value, error } = parseJson(params);
		if (error || !value || typeof value !== "object" || Array.isArray(value)) {
			problems.push("has Connector Params that are not a JSON object");
		}
	}
	return problems;
}

const PROBLEMS_BY_TYPE = {
	apply_workflow: applyWorkflowProblems,
	send_email: sendEmailProblems,
	update_field: updateFieldProblems,
	google_chat: googleChatProblems,
	push_notification: pushNotificationProblems,
	connector: connectorProblems,
};

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:ServiceTask") || !isExecutable(node)) {
			return;
		}
		const serviceType = attr(node, "serviceType");
		for (const problem of PROBLEMS_BY_TYPE[serviceType]?.(node) || []) {
			reporter.report(node.id, `Service Task "${label(node)}" (${serviceType}) ${problem}.`);
		}
	}

	return { check };
}
