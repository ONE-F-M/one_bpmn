import { test } from "vitest";
import assert from "node:assert/strict";

import { saveStatusLabel } from "@/utils/logixSaveStatus.js";

test("an empty or blank name asks for a name", () => {
	assert.equal(saveStatusLabel({ readonly: false, name: "", error: "" }), "Name the script to save it");
	assert.equal(saveStatusLabel({ readonly: false, name: "   ", error: "" }), "Name the script to save it");
	assert.equal(saveStatusLabel({ readonly: false, name: undefined, error: "" }), "Name the script to save it");
});

test("a read-only map says changes are not saved, even with a name", () => {
	assert.equal(
		saveStatusLabel({ readonly: true, name: "my_script", error: "" }),
		"Read-only map: changes are not saved",
	);
	assert.equal(
		saveStatusLabel({ readonly: true, name: "", error: "" }),
		"Read-only map: changes are not saved",
	);
});

test("a failed request shows the request's message", () => {
	assert.equal(saveStatusLabel({ readonly: false, name: "my_script", error: "Network down" }), "Network down");
});

test("no problem returns an empty string", () => {
	assert.equal(saveStatusLabel({ readonly: false, name: "my_script", error: "" }), "");
	assert.equal(saveStatusLabel({ readonly: false, name: "my_script" }), "");
});

test("a stale derived message is ignored once the cause is gone", () => {
	assert.equal(saveStatusLabel({ readonly: false, name: "my_script", error: "Name the script to save it" }), "");
	assert.equal(
		saveStatusLabel({ readonly: false, name: "my_script", error: "Read-only map: changes are not saved" }),
		"",
	);
});
