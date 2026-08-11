// Copyright (c) 2026, one-fm and contributors
// AG-UI SSE client for the shared AgentChatPanel (WI-001672).
//
// One turn = one streamed POST against the shared endpoint (WI-001670).
// POST, not EventSource: the turn context carries real payloads (ProsAlly's
// live canvas XML, Logix's linked script name, dialog grounding), and a GET
// puts all of it in the query string — nginx answered "414 Request-URI Too
// Large" the first time a genuine diagram rode a turn (observed live on
// staging, 2026-08-11). fetch() streams the same SSE body with the payload
// where it belongs; the read loop parses every `data:` line as one JSON
// event; RUN_FINISHED / RUN_ERROR terminate the turn; comment lines
// (keep-alives) are transport and never reach the callbacks.

const ENDPOINT = "/api/method/one_bpmn.api.agui.stream_agent_turn";

/**
 * Stream one agent turn.
 *
 * @param {Object} opts
 * @param {string} opts.agentId
 * @param {string} opts.message
 * @param {string} [opts.conversation]  omit on the first turn — the
 *        conversation id arrives on RUN_STARTED as thread_id
 * @param {Object} [opts.context]      host state for this turn
 * @param {(event: Object) => void} opts.onEvent   every parsed event
 * @param {(message: string) => void} opts.onError RUN_ERROR or transport failure
 * @param {() => void} opts.onDone     terminal — stream closed
 * @returns {{ close: () => void }}
 */
export function streamAgentTurn({ agentId, message, conversation, context, onEvent, onError, onDone }) {
	const controller = new AbortController();
	let finished = false;

	const finish = () => {
		if (finished) return;
		finished = true;
		controller.abort();
		onDone && onDone();
	};

	const handleLine = (line) => {
		if (finished || !line.startsWith("data:")) return; // comments/blanks = transport
		let event;
		try {
			event = JSON.parse(line.slice(5).trim());
		} catch (e) {
			return; // not ours — ignore, never break the transcript
		}
		const type = (event.type || "").toUpperCase();
		if (type === "RUN_ERROR") {
			onError && onError(event.message || "The agent failed to reply.");
			// RUN_FINISHED still follows per contract; wait for it.
			return;
		}
		onEvent && onEvent(event);
		if (type === "RUN_FINISHED") finish();
	};

	fetch(ENDPOINT, {
		method: "POST",
		credentials: "include",
		signal: controller.signal,
		headers: {
			"Content-Type": "application/json",
			"Accept": "text/event-stream",
			"X-Frappe-CSRF-Token": window.csrf_token || "",
		},
		body: JSON.stringify({
			agent_id: agentId,
			message,
			...(conversation ? { conversation } : {}),
			...(context && Object.keys(context).length ? { context } : {}),
		}),
	})
		.then(async (res) => {
			if (!res.ok || !res.body) {
				throw new Error(`The chat endpoint answered HTTP ${res.status}.`);
			}
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";
			for (;;) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				let nl;
				while ((nl = buffer.indexOf("\n")) >= 0) {
					handleLine(buffer.slice(0, nl).replace(/\r$/, ""));
					buffer = buffer.slice(nl + 1);
				}
			}
			if (buffer.trim()) handleLine(buffer.trim());
			finish(); // server closed without RUN_FINISHED — still terminal
		})
		.catch(() => {
			if (finished) return;
			onError && onError("Connection lost. Please try again.");
			finish();
		});

	return { close: finish };
}
