/** Flags a Send Email task with no subject or no body, which the engine fills with a generic default. */

import { is } from "bpmnlint-utils";

import { attr, isExecutable, label } from "../aiShapes.js";

export default function () {
	function check(node, reporter) {
		if (!is(node, "bpmn:ServiceTask") || attr(node, "serviceType") !== "send_email" || !isExecutable(node)) {
			return;
		}
		const missing = ["emailSubject", "emailBody"].filter((name) => !attr(node, name));
		if (missing.length) {
			const names = missing.map((name) => (name === "emailSubject" ? "subject" : "body")).join(" or ");
			reporter.report(node.id, `Send Email "${label(node)}" has no ${names}, so the email goes out with a generic default.`);
		}
	}

	return { check };
}
