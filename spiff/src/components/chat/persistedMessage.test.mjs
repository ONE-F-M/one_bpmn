// node --test spiff/src/components/chat/persistedMessage.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import { adoptPersistedName } from "./persistedMessage.js";

test("a streamed reply takes the name of the Chat Message it was saved as", () => {
	const items = [
		{ kind: "user", text: "hi" },
		{ kind: "agent", text: "earlier", message: "msg-earlier" },
		{ kind: "agent", text: "reply", message: "stream-uuid" },
	];
	adoptPersistedName(items, { stream_id: "stream-uuid", message_name: "6aorg9vdr2" });
	assert.equal(items[2].message, "6aorg9vdr2");
	assert.equal(items[1].message, "msg-earlier");
	assert.equal(items[0].message, undefined);
});
