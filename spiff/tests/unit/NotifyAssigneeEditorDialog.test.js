import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const tab = readFileSync(new URL("../../src/components/Notifications/NotifyTemplateTab.vue", import.meta.url), "utf8");

test("the email template picker comes before the HTML body", () => {
	const template = tab.indexOf("Pre-populate from Email Template");
	const body = tab.indexOf('label="HTML Body"');

	assert.ok(template > 0 && body > 0, "a field label was not found");
	assert.ok(template < body, "the HTML body is shown above the email template picker");
});
