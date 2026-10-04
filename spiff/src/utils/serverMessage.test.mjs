// node --test spiff/src/utils/serverMessage.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { serverMessage } from "./serverMessage.js";

test("the server's own message wins, without its markup", () => {
	const e = { messages: ["<b>That message no longer exists.</b>"], message: "/api/method/x DoesNotExistError" };
	assert.equal(serverMessage(e), "That message no longer exists.");
});

test("falls back to the error's message, then to a generic line", () => {
	assert.equal(serverMessage({ message: "Network down" }), "Network down");
	assert.equal(serverMessage({}), "Unknown error");
});
