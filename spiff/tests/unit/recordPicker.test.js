import { test } from "vitest";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import {
	canCreateRecord,
	isMissing,
	joinValues,
	splitValues,
	toOptions,
	valuesOf,
} from "@/utils/recordPicker.js";

const SRC = path.resolve(import.meta.dirname, "../../src");

function sourceFiles(dir) {
	return readdirSync(dir).flatMap((name) => {
		const full = path.join(dir, name);
		return statSync(full).isDirectory() ? sourceFiles(full) : [full];
	});
}

test("toOptions: maps rows by valueField and drops rows without a value", () => {
	const rows = [{ name: "A", title: "Alpha" }, { name: "" }, { id: "x", name: "B" }];
	assert.deepEqual(
		toOptions(rows, "name", (r) => r.title || r.name).map((o) => [o.value, o.label]),
		[
			["A", "Alpha"],
			["B", "B"],
		],
	);
});

test("multiple values round-trip through the comma-separated attribute", () => {
	assert.deepEqual(splitValues("a, b,,c"), ["a", "b", "c"]);
	assert.deepEqual(splitValues(""), []);
	assert.equal(joinValues(["a", "b"]), "a,b");
});

test("valuesOf: accepts options, plain values and empty selections", () => {
	assert.deepEqual(valuesOf([{ value: "a" }, "b"]), ["a", "b"]);
	assert.deepEqual(valuesOf({ value: "a" }), ["a"]);
	assert.deepEqual(valuesOf(null), []);
});

test("canCreateRecord: only a non-empty name that matches no option", () => {
	const options = [{ value: "Draft" }];
	assert.equal(canCreateRecord("draft", options), false);
	assert.equal(canCreateRecord("  ", options), false);
	assert.equal(canCreateRecord("Review", options), true);
});

test("isMissing: flags a value absent from a loaded list", () => {
	assert.equal(isMissing("Gone", [{ value: "Draft" }]), true);
	assert.equal(isMissing("Draft", [{ value: "Draft" }]), false);
	assert.equal(isMissing("Gone", []), false);
});

test("the three old pickers are gone and nothing imports them", () => {
	for (const name of ["FrappeAutocomplete", "FrappeMultiSelect", "RecordCombobox"]) {
		assert.equal(existsSync(path.join(SRC, "bpmn/shared", `${name}.js`)), false);
		for (const file of sourceFiles(SRC)) {
			assert.equal(
				readFileSync(file, "utf8").includes(name),
				false,
				`${file} still mentions ${name}`,
			);
		}
	}
});
