// node --test spiff/src/components/NotifyAssigneeEditorDialog.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const dialog = readFileSync(new URL("./NotifyAssigneeEditorDialog.vue", import.meta.url), "utf8");

test("the email template picker comes before the subject and the body", () => {
	const template = dialog.indexOf("Pre-populate from Email Template");
	const subject = dialog.indexOf(">\n\t\t\t\t\t\tSubject\n");
	const body = dialog.indexOf("Notification HTML Body");

	assert.ok(template > 0 && subject > 0 && body > 0, "a field label was not found");
	assert.ok(template < subject, "Subject is shown above the email template");
	assert.ok(subject < body);
});
