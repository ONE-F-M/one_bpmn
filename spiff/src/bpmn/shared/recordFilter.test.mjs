// node --test spiff/src/bpmn/shared/recordFilter.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { filterRecords } from "./recordFilter.js";

const RECORDS = [{ name: "Draft" }, { name: "Pending Approval" }, { name: "Approved" }];

test("an empty query lists every record and offers no create", () => {
	assert.deepEqual(filterRecords(RECORDS, "  "), { matches: RECORDS, canCreate: false });
});

test("a query filters by substring, case-insensitively, and offers creating a new name", () => {
	const { matches, canCreate } = filterRecords(RECORDS, "appro");
	assert.deepEqual(matches.map((s) => s.name), ["Pending Approval", "Approved"]);
	assert.equal(canCreate, true);
});

test("a name that already exists, in any case, is not offered for creation", () => {
	assert.equal(filterRecords(RECORDS, "approved").canCreate, false);
});
