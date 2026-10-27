// node --test spiff/src/components/chat/aguiClient.test.mjs
//
// the idle timer that fails a turn when neither a real event nor
// a `: keep-alive` SSE comment has arrived for a while, and the abort that
// timeout must trigger. Drives streamAgentTurn against a fake `fetch` whose
// stream reader is scripted frame by frame — no real network, no real 60s
// wait: idleTimeoutMs is passed short so the tests run in milliseconds.

import { test } from "node:test";
import assert from "node:assert/strict";

// aguiClient.js reaches into `window`/`document` only inside getCsrfToken(),
// called lazily at fetch time — a bare object is enough for a Node test.
globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || { cookie: "" };

const { streamAgentTurn } = await import("./aguiClient.js");

const encoder = new TextEncoder();

/** A fetch stub whose body reader replays `chunks` (strings), each after its
 * own `delayMs`, then reports done. A chunk that never arrives is modelled
 * as a promise that never resolves — the idle timer must fire before it. */
function fakeFetch(chunks) {
	let i = 0;
	const reader = {
		read() {
			if (i >= chunks.length) return Promise.resolve({ done: true, value: undefined });
			const { delayMs, text, hang } = chunks[i++];
			if (hang) return new Promise(() => {}); // never resolves — simulates a stuck connection
			return new Promise((resolve) =>
				setTimeout(() => resolve({ done: false, value: encoder.encode(text) }), delayMs).unref()
			);
		},
	};
	return () =>
		Promise.resolve({
			ok: true,
			body: { getReader: () => reader },
		});
}

/** Await onDone/onError, whichever fires first, with a generous safety cap
 * so a bug that never calls either fails the test instead of hanging it. */
function waitForOutcome() {
	let resolve;
	const outcome = new Promise((r) => (resolve = r));
	const cap = setTimeout(() => resolve({ timedOut: true }), 2000);
	cap.unref();
	return {
		outcome,
		onError: (message) => resolve({ error: message }),
		onDone: () => resolve((prev) => prev), // set by caller below when no error fires
	};
}

test("no event and no keep-alive within the idle window fails the turn with 'The agent did not respond'", async () => {
	const fetchStub = fakeFetch([{ hang: true }]);
	globalThis.fetch = fetchStub;

	let errorMessage = null;
	let done = false;
	const { close } = streamAgentTurn({
		agentId: "a",
		message: "hi",
		idleTimeoutMs: 30,
		onEvent: () => {},
		onError: (msg) => {
			errorMessage = msg;
		},
		onDone: () => {
			done = true;
		},
	});

	await new Promise((r) => setTimeout(r, 150).unref());

	assert.equal(errorMessage, "The agent did not respond");
	assert.equal(done, true, "onDone must still fire — the abort finishes the turn");
	close(); // idempotent; a real caller doesn't have to know it already finished
});

test("regular keep-alive comments reset the idle timer — a long turn completes normally", async () => {
	// Five keep-alive frames 40ms apart, well under the 30ms... no — under a
	// 100ms idle window each time, then the terminal event. Total wall time
	// (~200ms) is far past the 100ms window, but no single GAP exceeds it.
	const chunks = [
		{ delayMs: 40, text: ": keep-alive\n\n" },
		{ delayMs: 40, text: ": keep-alive\n\n" },
		{ delayMs: 40, text: ": keep-alive\n\n" },
		{ delayMs: 40, text: ": keep-alive\n\n" },
		{ delayMs: 40, text: 'data: {"type":"RUN_FINISHED"}\n\n' },
	];
	globalThis.fetch = fakeFetch(chunks);

	let errorMessage = null;
	let done = false;
	const events = [];
	streamAgentTurn({
		agentId: "a",
		message: "hi",
		idleTimeoutMs: 100,
		onEvent: (e) => events.push(e),
		onError: (msg) => {
			errorMessage = msg;
		},
		onDone: () => {
			done = true;
		},
	});

	await new Promise((r) => setTimeout(r, 400).unref());

	assert.equal(errorMessage, null, "keep-alives must have kept the connection from timing out");
	assert.equal(done, true);
});

// A stream that dies mid-turn: the first read delivers RUN_STARTED, the second
// throws. `statuses` are what turn_status answers, one per poll.
function droppedStreamFetch({ statuses, runStarted = true }) {
	let polls = 0;
	return (url) => {
		if (String(url).includes("turn_status")) {
			const status = statuses[Math.min(polls++, statuses.length - 1)];
			return Promise.resolve({ ok: true, json: () => Promise.resolve({ message: status }) });
		}
		let reads = 0;
		const frame = runStarted ? 'data: {"type":"RUN_STARTED","threadId":"conv-1"}\n\n' : ": keep-alive\n\n";
		return Promise.resolve({
			ok: true,
			body: {
				getReader: () => ({
					read: () =>
						reads++ === 0
							? Promise.resolve({ done: false, value: encoder.encode(frame) })
							: Promise.reject(new TypeError("network error")),
				}),
			},
		});
	};
}

function runDropped(fetchStub) {
	globalThis.fetch = fetchStub;
	const result = { events: [], error: null, done: false };
	streamAgentTurn({
		agentId: "a",
		message: "hi",
		clientMessageId: "m-1",
		recoverIntervalMs: 5,
		onEvent: (e) => result.events.push(e),
		onError: (msg) => (result.error = msg),
		onDone: () => (result.done = true),
	});
	return result;
}

test("a dropped stream waits for the running turn and replays its reply instead of failing", async () => {
	const result = runDropped(
		droppedStreamFetch({
			statuses: [
				{ state: "running" },
				{
					state: "done",
					replies: [
						{
							message: "msg-1",
							text: "Redrawn.",
							events: [{ name: "onefm.choice", value: { options: ["Yes"] } }],
						},
					],
				},
			],
		})
	);

	await new Promise((r) => setTimeout(r, 120));

	assert.equal(result.error, null, "a reply that was saved must not surface as 'Connection lost'");
	assert.equal(result.done, true);
	assert.deepEqual(
		result.events.map((e) => e.type),
		["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "CUSTOM"]
	);
	assert.equal(result.events[2].delta, "Redrawn.");
	assert.equal(result.events[1].messageId, "msg-1");
});

test("a dropped stream whose turn is lost still reports 'Connection lost'", async () => {
	const result = runDropped(droppedStreamFetch({ statuses: [{ state: "lost" }] }));

	await new Promise((r) => setTimeout(r, 80));

	assert.equal(result.error, "Connection lost. Please try again.");
	assert.equal(result.done, true);
});

test("a stream that drops before the conversation is known fails without polling", async () => {
	let polled = false;
	const inner = droppedStreamFetch({ statuses: [{ state: "done", replies: [] }], runStarted: false });
	const result = runDropped((url) => {
		if (String(url).includes("turn_status")) polled = true;
		return inner(url);
	});

	await new Promise((r) => setTimeout(r, 60));

	assert.equal(result.error, "Connection lost. Please try again.");
	assert.equal(polled, false);
});
