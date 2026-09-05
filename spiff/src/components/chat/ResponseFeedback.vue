<template>
	<!-- One row under an agent reply. Quiet by default: the buttons carry no
	     background until they are hovered, focused or chosen, so a transcript of
	     twenty replies does not read as twenty toolbars. -->
	<div class="arf" :class="{ 'arf--open': panelOpen }">
		<div class="arf-row" role="group" :aria-label="__('Rate this reply')">
			<button
				type="button"
				class="arf-btn"
				:class="{ 'arf-btn--on': rating === 'Positive' }"
				:aria-pressed="rating === 'Positive'"
				:aria-label="rating === 'Positive' ? __('Remove your good rating') : __('Good reply')"
				:title="rating === 'Positive' ? __('Remove your good rating') : __('Good reply')"
				:disabled="busy"
				@click="choose('Positive')"
			>
				<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
					<path
						d="M6.2 14V6.6L9 1.6c.6.1 1 .6 1 1.2V6h3.2c.8 0 1.4.7 1.2 1.5l-1.1 5c-.1.6-.7 1-1.3 1H6.2zM4.6 14H2.4c-.5 0-.9-.4-.9-.9V7.5c0-.5.4-.9.9-.9h2.2V14z"
					/>
				</svg>
			</button>

			<button
				type="button"
				class="arf-btn"
				:class="{ 'arf-btn--on arf-btn--bad': rating === 'Negative' }"
				:aria-pressed="rating === 'Negative'"
				:aria-label="rating === 'Negative' ? __('Remove your poor rating') : __('Poor reply')"
				:title="rating === 'Negative' ? __('Remove your poor rating') : __('Poor reply')"
				:aria-expanded="panelOpen"
				:disabled="busy"
				@click="choose('Negative')"
			>
				<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
					<path
						d="M9.8 2v7.4L7 14.4c-.6-.1-1-.6-1-1.2V10H2.8c-.8 0-1.4-.7-1.2-1.5l1.1-5c.1-.6.7-1 1.3-1h5.8zM11.4 2h2.2c.5 0 .9.4.9.9v5.6c0 .5-.4.9-.9.9h-2.2V2z"
					/>
				</svg>
			</button>

			<!-- The whole acknowledgement. No modal, no thank-you message. -->
			<span v-if="saved" class="arf-ack" role="status">{{ __("Thanks") }}</span>
		</div>

		<!-- Reasons appear only after a thumbs down. Unlike the old flow, nothing
		     here has been saved yet — a Negative rating needs a comment before it
		     records anything at all. -->
		<div v-if="panelOpen" ref="panelEl" class="arf-panel" @keydown.esc.stop="closePanel">
			<div class="arf-panel-head">{{ __("What was wrong? (required)") }}</div>
			<div class="arf-chips" role="group" :aria-label="__('Reasons')">
				<button
					v-for="option in REASONS"
					:key="option"
					type="button"
					class="arf-chip"
					:class="{ 'arf-chip--on': reasons.includes(option) }"
					:aria-pressed="reasons.includes(option)"
					:disabled="busy"
					@click="toggleReason(option)"
				>
					{{ __(option) }}
				</button>
			</div>
			<textarea
				v-model="comment"
				class="arf-comment"
				:class="{ 'arf-comment--error': commentError }"
				rows="2"
				:maxlength="2000"
				:placeholder="__('What went wrong?')"
				:aria-label="__('What went wrong?')"
				:aria-required="true"
				@input="commentError = false"
			/>
			<div v-if="commentError" class="arf-comment-error" role="alert">
				{{ __("A comment is required for a poor rating.") }}
			</div>
			<div class="arf-panel-foot">
				<button type="button" class="arf-send" :disabled="busy" @click="submitNegative">
					{{ __("Send") }}
				</button>
				<button type="button" class="arf-skip" :disabled="busy" @click="closePanel">
					{{ __("Cancel") }}
				</button>
			</div>
		</div>
	</div>
</template>

<script setup>
// Rating one agent reply (WI-001822).
//
// The record, the endpoint and the identifiers are WI-001641's; this component
// only asks and shows. It owns no opinion about storage, and it never invents an
// id — a reply with no `message` gets no control, because there would be nothing
// to attach the answer to.
//
// Deliberate choices:
//
//  * A Positive thumb POSTS immediately — a single click is already a
//    complete rating, and there is nothing to require from it.
//  * A Negative thumb does NOT post on click. It only opens the panel: a
//    poor rating requires a comment (a Process Owner gets assigned and
//    notified from this record, and an empty complaint tells them nothing),
//    so nothing is recorded until the panel is submitted with one.
//  * Withdrawing an existing rating (clicking the thumb already chosen)
//    always clears immediately, on either thumb — no comment needed to
//    take back a rating.
//  * The state shown is the user's OWN rating, not a tally. This is a way to
//    tell us something, not a score to compare yourself against.
import { nextTick, ref, watch } from "vue";
import { frappeRequest } from "frappe-ui";

const props = defineProps({
	message: { type: String, required: true },
	initialRating: { type: String, default: "" },
});
const emit = defineEmits(["rated"]);

const REASONS = [
	"Inaccurate",
	"Incomplete",
	"Not relevant",
	"Didn't follow instructions",
	"Wrong tone",
];

const __ = (s) => (window.__ && typeof window.__ === "function" ? window.__(s) : s);

const rating = ref(props.initialRating || "");
const reasons = ref([]);
const comment = ref("");
const panelOpen = ref(false);
const busy = ref(false);
const saved = ref(false);
const panelEl = ref(null);
const commentError = ref(false);

// A resumed conversation learns its ratings after the bubbles are drawn.
watch(
	() => props.initialRating,
	(value) => {
		if (!busy.value) rating.value = value || "";
	}
);

let ackTimer = null;
function acknowledge() {
	saved.value = true;
	clearTimeout(ackTimer);
	ackTimer = setTimeout(() => (saved.value = false), 1600);
}

function call(method, body) {
	return frappeRequest({
		url: `/api/method/one_bpmn.api.feedback.${method}`,
		method: "POST",
		params: { message: props.message, ...body },
	});
}

async function choose(next) {
	if (busy.value || !props.message) return;

	// Clicking the thumb you already chose withdraws it. An unrated reply has no
	// record at all, which is what keeps "nobody said anything" different from
	// "somebody disliked it" — so this really does clear, and needs no comment
	// to do it, on either thumb.
	if (rating.value === next) {
		const previous = rating.value;
		rating.value = "";
		panelOpen.value = false;
		reasons.value = [];
		comment.value = "";
		commentError.value = false;

		busy.value = true;
		try {
			await call("clear_response_rating", {});
			acknowledge();
			emit("rated", { message: props.message, rating: "" });
		} catch (e) {
			rating.value = previous;
		} finally {
			busy.value = false;
		}
		return;
	}

	if (next === "Negative") {
		// Nothing saves on this click. A Negative rating requires a comment, so
		// the record is only created once the panel below is submitted with one.
		reasons.value = [];
		comment.value = "";
		commentError.value = false;
		panelOpen.value = true;
		await nextTick();
		panelEl.value?.querySelector("button")?.focus();
		return;
	}

	// Positive still saves instantly — a single click is already a complete
	// rating, and there is nothing to require from it.
	const previous = rating.value;
	rating.value = next;
	busy.value = true;
	try {
		await call("rate_response", { rating: next });
		acknowledge();
		emit("rated", { message: props.message, rating: rating.value });
	} catch (e) {
		rating.value = previous;
	} finally {
		busy.value = false;
	}
}

function toggleReason(option) {
	const at = reasons.value.indexOf(option);
	if (at === -1) reasons.value.push(option);
	else reasons.value.splice(at, 1);
}

async function submitNegative() {
	if (busy.value) return;
	if (!comment.value.trim()) {
		commentError.value = true;
		return;
	}
	commentError.value = false;
	busy.value = true;
	try {
		await call("rate_response", {
			rating: "Negative",
			reasons: JSON.stringify(reasons.value),
			comment: comment.value,
		});
		rating.value = "Negative";
		acknowledge();
		emit("rated", { message: props.message, rating: "Negative" });
		panelOpen.value = false;
	} catch (e) {
		// Keep the panel open — whatever was typed is not lost, and the rating
		// was never recorded, so there is nothing to roll back.
	} finally {
		busy.value = false;
	}
}

function closePanel() {
	panelOpen.value = false;
}
</script>

<style scoped>
.arf {
	margin: 2px 0 6px 2px;
}
.arf-row {
	display: flex;
	align-items: center;
	gap: 2px;
	/* Invisible until the reply is hovered or something here has focus, so the
	   transcript stays a transcript. */
	opacity: 0;
	transition: opacity 0.12s ease-in-out;
}
.arf:hover .arf-row,
.arf--open .arf-row,
.arf-row:focus-within {
	opacity: 1;
}
/* Never hide a rating the user already gave. */
.arf-row:has(.arf-btn--on) {
	opacity: 1;
}
.arf-btn {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 22px;
	height: 22px;
	padding: 0;
	border: none;
	border-radius: 4px;
	background: transparent;
	color: var(--gray-500, #8d8d8d);
	cursor: pointer;
}
.arf-btn svg {
	width: 13px;
	height: 13px;
	fill: currentColor;
}
.arf-btn:hover:not(:disabled) {
	background: var(--gray-100, #f0f0f0);
	color: var(--gray-700, #4f4f4f);
}
.arf-btn:focus-visible {
	outline: 2px solid var(--blue-400, #6ba6ff);
	outline-offset: 1px;
}
.arf-btn:disabled {
	cursor: default;
	opacity: 0.5;
}
.arf-btn--on {
	color: var(--green-600, #2f9461);
	background: var(--green-50, #eafaf1);
}
.arf-btn--bad.arf-btn--on {
	color: var(--red-600, #d1483b);
	background: var(--red-50, #fdeeec);
}
.arf-ack {
	margin-left: 4px;
	font-size: 11px;
	color: var(--gray-500, #8d8d8d);
}
.arf-panel {
	margin-top: 6px;
	padding: 8px;
	border: 1px solid var(--gray-200, #e4e4e4);
	border-radius: 6px;
	background: var(--gray-50, #fafafa);
	max-width: 420px;
}
.arf-panel-head {
	font-size: 11px;
	color: var(--gray-600, #6b6b6b);
	margin-bottom: 6px;
}
.arf-chips {
	display: flex;
	flex-wrap: wrap;
	gap: 4px;
}
.arf-chip {
	font-size: 11px;
	padding: 3px 8px;
	border: 1px solid var(--gray-300, #d1d1d1);
	border-radius: 999px;
	background: white;
	color: var(--gray-700, #4f4f4f);
	cursor: pointer;
}
.arf-chip:hover:not(:disabled) {
	border-color: var(--gray-500, #8d8d8d);
}
.arf-chip:focus-visible {
	outline: 2px solid var(--blue-400, #6ba6ff);
	outline-offset: 1px;
}
.arf-chip--on {
	background: var(--gray-800, #333);
	border-color: var(--gray-800, #333);
	color: white;
}
.arf-comment {
	width: 100%;
	margin-top: 6px;
	padding: 5px 6px;
	font: inherit;
	font-size: 12px;
	border: 1px solid var(--gray-300, #d1d1d1);
	border-radius: 4px;
	resize: vertical;
	box-sizing: border-box;
}
.arf-comment--error {
	border-color: var(--red-500, #e0473f);
}
.arf-comment-error {
	margin-top: 4px;
	font-size: 11px;
	color: var(--red-600, #d1483b);
}
.arf-panel-foot {
	display: flex;
	gap: 6px;
	margin-top: 6px;
}
.arf-send,
.arf-skip {
	font-size: 11px;
	padding: 4px 10px;
	border-radius: 4px;
	cursor: pointer;
}
.arf-send {
	border: none;
	background: var(--gray-800, #333);
	color: white;
}
.arf-skip {
	border: 1px solid var(--gray-300, #d1d1d1);
	background: white;
	color: var(--gray-700, #4f4f4f);
}
.arf-send:focus-visible,
.arf-skip:focus-visible {
	outline: 2px solid var(--blue-400, #6ba6ff);
	outline-offset: 1px;
}
</style>
