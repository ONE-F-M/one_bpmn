import { test } from "vitest";
import assert from "node:assert/strict";

import {
	agentLabel,
	errorText,
	fmt,
	fmtCost,
	round1,
	runPill,
	sparklinePoints,
} from "@/utils/evalFormat.js";

test("fmt and fmtCost treat empty values as zero", () => {
	assert.equal(fmt(null), "0");
	assert.equal(fmt(12345), "12,345");
	assert.equal(fmtCost(undefined), "$0.00");
	assert.equal(fmtCost(0.00123), "$0.0012");
});

test("round1 rounds to one decimal and survives junk", () => {
	assert.equal(round1(66.666), 66.7);
	assert.equal(round1("x"), 0);
});

test("runPill colours each status family", () => {
	assert.match(runPill("Passed"), /green/);
	for (const s of ["Failed", "Error", "Timed Out", "Invalid"])
		assert.match(runPill(s), /red/, s);
	assert.match(runPill("Running"), /animate-pulse/);
	assert.match(runPill("Queued"), /gray/);
});

test("sparklinePoints needs two points and scales 0-100 into the box", () => {
	assert.equal(sparklinePoints(null), null);
	assert.equal(sparklinePoints([50]), null);
	assert.equal(sparklinePoints([0, 100]), "0.0,20.0 100.0,0.0");
});

test("agentLabel names the lifecycle state and a disabled agent", () => {
	assert.equal(agentLabel({ name: "A1", lifecycle_status: "Live" }), "A1");
	assert.equal(
		agentLabel({ name: "A1", agent_name: "Nova", lifecycle_status: "Draft", enabled: 0 }),
		"Nova — Draft, disabled",
	);
});

test("errorText prefers server messages, then the error message, then the fallback", () => {
	assert.equal(errorText({ messages: ["a", "b"], message: "x" }, "f"), "a b");
	assert.equal(errorText({ message: "x" }, "f"), "x");
	assert.equal(errorText({}, "f"), "f");
});
