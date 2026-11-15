import { describe, expect, it } from "vitest";
import {
	clarificationLabel,
	clarificationTheme,
	delegationTheme,
	describeAgo,
	directionTheme,
	initiator,
	isTerminal,
	limitLabel,
	stateTheme,
	statusTheme,
	taskBrief,
} from "../../src/utils/a2aFormat";
import { deskUrl } from "../../src/utils/deskUrl";

describe("describeAgo", () => {
	it("uses seconds, minutes and hours", () => {
		expect(describeAgo(45)).toBe("45s");
		expect(describeAgo(600)).toBe("10 minutes");
		expect(describeAgo(7200)).toBe("2.0 hours");
	});

	it("treats a missing value as zero", () => {
		expect(describeAgo(null)).toBe("0s");
	});
});

describe("themes", () => {
	it("maps approval status", () => {
		expect(statusTheme("Approved")).toBe("green");
		expect(statusTheme("Revoked")).toBe("red");
		expect(statusTheme("Draft")).toBe("gray");
	});

	it("maps task state", () => {
		expect(stateTheme("completed")).toBe("green");
		expect(stateTheme("timed-out")).toBe("red");
		expect(stateTheme("input-required")).toBe("orange");
		expect(stateTheme("canceled")).toBe("gray");
		expect(stateTheme("working")).toBe("blue");
	});

	it("maps direction, with Internal as the neutral case", () => {
		expect(directionTheme("Inbound")).toBe("blue");
		expect(directionTheme("Outbound")).toBe("green");
		expect(directionTheme("Internal")).toBe("gray");
	});

	it("maps delegation status", () => {
		expect(delegationTheme("Completed")).toBe("green");
		expect(delegationTheme("Failed")).toBe("red");
		expect(delegationTheme("Needs Review")).toBe("orange");
		expect(delegationTheme("In Progress")).toBe("blue");
		expect(delegationTheme("Cancelled")).toBe("gray");
		expect(delegationTheme("Delegated")).toBe("gray");
	});
});

describe("clarifications", () => {
	it("colours a chased question as worse news than a fresh one", () => {
		expect(clarificationTheme({ status: "Awaiting Answer" })).toBe("orange");
		expect(clarificationTheme({ status: "Awaiting Answer", escalated_at: "x" })).toBe("red");
		expect(clarificationTheme({ status: "Answered" })).toBe("green");
		expect(clarificationTheme(null)).toBe("gray");
	});

	it("labels a waiting question by how far it was chased", () => {
		expect(clarificationLabel({ status: "Awaiting Answer" })).toBe("Awaiting answer");
		expect(clarificationLabel({ status: "Awaiting Answer", reminded_at: "x" })).toBe(
			"Reminded",
		);
		expect(
			clarificationLabel({ status: "Awaiting Answer", reminded_at: "x", escalated_at: "y" }),
		).toBe("Escalated");
		expect(clarificationLabel({ status: "Answered" })).toBe("Answered");
	});
});

describe("tasks", () => {
	it("knows which states are final", () => {
		expect(isTerminal("failed")).toBe(true);
		expect(isTerminal("working")).toBe(false);
	});

	it("reads the instruction from the stored payload", () => {
		expect(taskBrief({ request_payload: '{"instruction":"do it"}' })).toBe("do it");
		expect(taskBrief({ request_payload: '{"text":"hello"}' })).toBe("hello");
	});

	it("falls back to the raw payload when it is not JSON", () => {
		expect(taskBrief({ request_payload: "not json" })).toBe("not json");
		expect(taskBrief({})).toBe("");
	});

	it("names the delegating agent first, and never leaves it blank", () => {
		expect(initiator({ delegated_by: "A", client: "C", remote_agent: "R" })).toBe("A");
		expect(initiator({ client: "C" })).toBe("C");
		expect(initiator({})).toBe("—");
	});

	it("labels a limit in the words the notification uses", () => {
		expect(limitLabel("max_recursion_depth")).toBe("nesting depth");
		expect(limitLabel("something_new")).toBe("something_new");
	});
});

describe("deskUrl", () => {
	it("slugs the doctype and encodes the name", () => {
		expect(deskUrl("A2A Task", "A2A-17522")).toBe("/app/a2a-task/A2A-17522");
		expect(deskUrl("Sales Order", "SO 1/2")).toBe("/app/sales-order/SO%201%2F2");
	});
});
