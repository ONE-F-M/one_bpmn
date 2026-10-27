// Copyright (c) 2026, one-fm and contributors
// AG-UI SSE client for the shared AgentChatPanel (WI-001672).
//
// One turn = one POST against the shared endpoint, read as a stream.
//
// It used to be an EventSource GET, and EventSource cannot POST — so the whole
// turn had to travel in the query string, including `context.current_xml`, the
// entire canvas. On a real diagram that is fatal: the ProsAlly panel sends the
// live BPMN on every message, and ~50KB of XML percent-encodes to well over
// 150KB (every `<` becomes %3C, every quote %5C%22). The server rejects the
// request line before any of our code runs, so the designer got a bare
// "414 Request-URI Too Long" error page instead of a reply. Small maps stayed
// under the limit, which is why it surfaced only once the diagrams grew; nginx
// would have refused it in production at ~8KB regardless.
//
// fetch + POST puts the payload in the BODY, where there is no such ceiling.
// The endpoint is @frappe.whitelist() with no method restriction, so it already
// accepted POST — this is a client-side change only.
//
// The read loop mirrors the production-proven parsing in onefm_mcp's
// chat_widget.js, reduced to what the panel consumes: every `data:` line is one
// JSON event; RUN_FINISHED / RUN_ERROR terminate the turn; comment lines
// (keep-alives) are transport and never reach the callbacks.

import { frappeGet, getCsrfToken } from "../../bpmn/shared/frappeResource.js";

const ENDPOINT = "/api/method/one_bpmn.api.agui.stream_agent_turn";

const STATUS_ENDPOINT = "/api/method/one_bpmn.api.agui.turn_status";

const GENERIC_FAILURE = "Connection lost. Please try again.";

// A dropped stream does not stop the turn: it keeps running on the worker and
// saves its reply. The client asks for that reply instead of reporting a failure,
// for as long as a queued AI job may live (30 min job limit plus a minute).
const RECOVER_INTERVAL_MS = 3000;
const RECOVER_MAX_MS = 31 * 60 * 1000;
const RECOVER_MAX_STATUS_ERRORS = 10;

// the server sends a `: keep-alive` SSE comment every 10s during a
// buffered turn, on top of whatever real events it produces. If NEITHER kind
// of frame has arrived for this long, the connection is stuck — fail the
// turn instead of leaving the panel on "Thinking…" forever.
const DEFAULT_IDLE_TIMEOUT_MS = 60000;
const TIMEOUT_FAILURE = "The agent did not respond";

/**
 * Stream one agent turn.
 *
 * @param {Object} opts
 * @param {string} opts.agentId
 * @param {string} opts.message
 * @param {string} [opts.conversation]  omit on the first turn — the
 *        conversation id arrives on RUN_STARTED as thread_id
 * @param {Object} [opts.context]      host state for this turn
 * @param {string} [opts.clientMessageId] id minted for this message. Re-sending
 *        it replays the first reply instead of running the agent a second time.
 * @param {(event: Object) => void} opts.onEvent   every parsed event
 * @param {(message: string) => void} opts.onError RUN_ERROR or transport failure
 * @param {() => void} opts.onDone     terminal — stream closed
 * @param {number} [opts.idleTimeoutMs] no event/keep-alive for this long
 *        fails the turn; defaults to 60000 (60s), well past the server's
 *        10s keep-alive cadence.
 * @param {number} [opts.recoverIntervalMs] how often a dropped stream asks
 *        whether its turn has a reply; defaults to 3000.
 * @returns {{ close: () => void }}
 */
export function streamAgentTurn({
	agentId,
	message,
	conversation,
	context,
	clientMessageId,
	onEvent,
	onError,
	onDone,
	idleTimeoutMs,
	recoverIntervalMs,
}) {
	const controller = new AbortController();
	let finished = false;
	let threadId = conversation || "";

	const IDLE_TIMEOUT_MS = idleTimeoutMs || DEFAULT_IDLE_TIMEOUT_MS;
	let idleTimer = null;

	const clearIdleTimer = () => {
		if (idleTimer) clearTimeout(idleTimer);
		idleTimer = null;
	};

	// Called on every frame the transport actually delivers — a parsed
	// event AND a bare keep-alive comment both count as "still alive".
	const resetIdleTimer = () => {
		clearIdleTimer();
		idleTimer = setTimeout(() => fail(TIMEOUT_FAILURE), IDLE_TIMEOUT_MS);
	};

	const finish = () => {
		if (finished) return;
		finished = true;
		clearIdleTimer();
		controller.abort();
		onDone && onDone();
	};

	const fail = (text) => {
		if (finished) return;
		onError && onError(text);
		finish();
	};

	// One frame may carry several `data:` lines; a line starting with `:` is a
	// keep-alive comment and is transport, not content.
	const handleFrame = (frame) => {
		const data = frame
			.split("\n")
			.filter((line) => line.startsWith("data:"))
			.map((line) => line.slice(5).trim())
			.join("\n");
		if (!data) return;

		let event;
		try {
			event = JSON.parse(data);
		} catch (e) {
			return; // not ours — ignore, never break the transcript
		}

		const type = (event.type || "").toUpperCase();
		if (type === "RUN_STARTED") threadId = event.threadId || event.thread_id || threadId;
		if (type === "RUN_ERROR") {
			onError && onError(event.message || "The agent failed to reply.");
			// RUN_FINISHED still follows per contract; wait for it.
			return;
		}
		onEvent && onEvent(event);
		if (type === "RUN_FINISHED") finish();
	};

	// Replays a turn that finished while the stream was down, as the events it
	// would have streamed.
	const replay = (replies) => {
		replies.forEach(({ message: messageId, text, events }) => {
			if (text) {
				onEvent && onEvent({ type: "TEXT_MESSAGE_START", messageId, role: "assistant" });
				onEvent && onEvent({ type: "TEXT_MESSAGE_CONTENT", messageId, delta: text });
				onEvent && onEvent({ type: "TEXT_MESSAGE_END", messageId });
			}
			(events || []).forEach(({ name, value }) => onEvent && onEvent({ type: "CUSTOM", name, value }));
		});
	};

	// Ask the server for the reply of a turn whose stream dropped. True when the
	// turn was settled here (replayed); false when there is nothing to recover.
	const recover = async () => {
		if (!threadId || !clientMessageId) return false;
		clearIdleTimer();
		const waitMs = recoverIntervalMs || RECOVER_INTERVAL_MS;
		const deadline = Date.now() + RECOVER_MAX_MS;
		let statusErrors = 0;
		while (!finished && Date.now() < deadline) {
			await new Promise((resolve) => setTimeout(resolve, waitMs));
			if (finished) return true;
			let status;
			try {
				status = await frappeGet(STATUS_ENDPOINT, {
					conversation: threadId,
					client_message_id: clientMessageId,
				});
			} catch (e) {
				status = null;
			}
			if (!status || !status.state) {
				statusErrors += 1;
				if (statusErrors >= RECOVER_MAX_STATUS_ERRORS) return false;
				continue;
			}
			statusErrors = 0;
			if (status.state === "running") continue;
			if (status.state !== "done") return false;
			replay(status.replies || []);
			finish();
			return true;
		}
		return false;
	};

	const recoverOrFail = async () => {
		if (!(await recover())) fail(GENERIC_FAILURE);
	};

	const body = new URLSearchParams({ agent_id: agentId, message: message ?? "" });
	if (conversation) body.set("conversation", conversation);
	if (clientMessageId) body.set("client_message_id", clientMessageId);
	if (context && Object.keys(context).length) body.set("context", JSON.stringify(context));

	(async () => {
		let response;
		try {
			response = await fetch(ENDPOINT, {
				method: "POST",
				credentials: "same-origin",
				headers: {
					"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
					Accept: "text/event-stream",
					"X-Frappe-CSRF-Token": getCsrfToken(),
				},
				body: body.toString(),
				signal: controller.signal,
			});
		} catch (e) {
			await recoverOrFail();
			return;
		}

		if (!response.ok || !response.body) {
			fail(await describeFailure(response));
			return;
		}

		// The connection is live from here — arm the idle timer before the
		// first read, so a turn that never sends anything still times out.
		resetIdleTimer();

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";

		try {
			for (;;) {
				const { value, done } = await reader.read();
				if (done) break;
				// Any bytes at all — a real event or a bare `: keep-alive`
				// comment — prove the connection is still alive.
				resetIdleTimer();
				buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

				// SSE frames are separated by a blank line.
				let boundary = buffer.indexOf("\n\n");
				while (boundary !== -1) {
					handleFrame(buffer.slice(0, boundary));
					buffer = buffer.slice(boundary + 2);
					if (finished) return; // RUN_FINISHED — stop reading
					boundary = buffer.indexOf("\n\n");
				}
			}
		} catch (e) {
			if (finished) return; // our own abort unwinding the reader
			await recoverOrFail();
			return;
		}

		// Stream closed without RUN_FINISHED: flush a trailing frame, then end
		// the turn so the panel never stays stuck on "streaming".
		if (buffer.trim()) handleFrame(buffer);
		finish();
	})();

	return { close: finish };
}

/**
 * Turn a failed response into something the designer can act on. Frappe reports
 * a refusal (permission, throttle, frozen conversation) as JSON with the message
 * under `exception` or `_server_messages`; anything else falls back to the status.
 */
async function describeFailure(response) {
	let raw = "";
	try {
		raw = await response.text();
	} catch (e) {
		return GENERIC_FAILURE;
	}

	try {
		const payload = JSON.parse(raw);
		const serverMessages = payload._server_messages ? JSON.parse(payload._server_messages) : [];
		for (const entry of serverMessages) {
			const parsed = typeof entry === "string" ? JSON.parse(entry) : entry;
			if (parsed && parsed.message) return stripTags(parsed.message);
		}
		if (payload.exception) return stripTags(String(payload.exception));
		if (payload.message) return stripTags(String(payload.message));
	} catch (e) {
		// not JSON — fall through to the status line
	}

	if (response.status === 403) return "You do not have permission to use this agent.";
	return `The agent could not be reached (${response.status}).`;
}

function stripTags(text) {
	return text.replace(/<[^>]*>/g, "").trim() || GENERIC_FAILURE;
}
