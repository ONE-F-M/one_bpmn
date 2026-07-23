<!--
  AgentThinkingIndicator
  ----------------------
  Shared "working" indicator for the agent chat panels (ProsAlly, Docu, Logix).
  Replaces the old static three-dot ellipsis with a rotating status line so a
  long turn feels alive. Rendered under `v-if="isTyping"` in each panel — it is
  mounted when a turn starts and unmounted when it ends, so the rotation timer
  is created on mount and cleared on unmount (no orphaned timers).

  It inherits the host bubble's colour/typography (color: inherit + currentColor)
  so it looks native in every panel and in light/dark. The phrase swap fades and
  a small dot pulses; both are silenced under prefers-reduced-motion while the
  text keeps rotating. The label is exposed as polite live text for assistive tech.

  v1 is purely time-based — the status endpoints expose no per-stage signal yet.
  Surfacing the real pipeline stage ("Classifying intent…", "Writing script…")
  is a deliberate phase-2 follow-up.
-->
<template>
	<div class="ati" role="status" aria-live="polite">
		<span class="ati-pulse" aria-hidden="true"></span>
		<transition name="ati-swap" mode="out-in">
			<span class="ati-text" :key="phrase">{{ phrase }}</span>
		</transition>
	</div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from "vue";

// ── The one place to tune the wording ────────────────────────────────
// Short, playful "working" phrases. Edit this array freely — nothing below
// depends on specific entries. Keep them short, on-brand, and tasteful.
const PHRASES = [
	"Thinking…",
	"Pondering…",
	"Fibbergisting…",
	"Noodling…",
	"Mulling it over…",
	"Percolating…",
	"Cogitating…",
	"Untangling…",
	"Connecting the dots…",
	"Ruminating…",
	"Conjuring…",
	"Deliberating…",
	"Brainstorming…",
	"Musing…",
	"Contemplating…",
	"Reasoning…",
	"Puzzling it out…",
	"Weighing options…",
	"Wrangling ideas…",
	"Sketching it out…",
	"Piecing it together…",
	"Working it through…",
	"Chewing on it…",
	"Simmering…",
	"Marinating…",
	"Brewing…",
	"Whirring…",
	"Ticking away…",
	"Crunching…",
	"Number-crunching…",
	"Calculating…",
	"Computing…",
	"Processing…",
	"Parsing…",
	"Digesting…",
	"Synthesizing…",
	"Distilling…",
	"Untying knots…",
	"Following the thread…",
	"Joining the dots…",
	"Mapping it out…",
	"Charting a path…",
	"Plotting…",
	"Scheming…",
	"Strategizing…",
	"Devising…",
	"Formulating…",
	"Drafting…",
	"Composing…",
	"Assembling…",
	"Constructing…",
	"Tinkering…",
	"Fiddling…",
	"Wiring things up…",
	"Turning gears…",
	"Spinning up…",
	"Warming up…",
	"Gathering thoughts…",
	"Rounding up ideas…",
	"Herding thoughts…",
	"Cooking something up…",
	"Hatching a plan…",
	"Dreaming it up…",
	"Imagining…",
	"Envisioning…",
	"Visualizing…",
	"Reflecting…",
	"Meditating on it…",
	"Considering…",
	"Weighing it up…",
	"Sizing it up…",
	"Sifting through…",
	"Combing through…",
	"Poring over it…",
	"Scanning…",
	"Surveying…",
	"Investigating…",
	"Exploring…",
	"Probing…",
	"Digging in…",
	"Unpacking it…",
	"Decoding…",
	"Deciphering…",
	"Untangling threads…",
	"Threading the needle…",
	"Bridging ideas…",
	"Wibbling…",
	"Wobbulating…",
	"Flumdiddling…",
	"Whizbanging…",
	"Cerebrating…",
	"Ideating…",
	"Percolating harder…",
	"Almost there…",
	"Nearly ready…",
	"Wrapping up…",
];

// How often the phrase advances. One fixed interval, per spec.
const ROTATE_MS = 2200;

const phrase = ref(PHRASES[0]);
let idx = 0;
let timer = null;

function pickDifferent() {
	// Never show the same word twice in a row.
	if (PHRASES.length < 2) return idx;
	let next = idx;
	while (next === idx) {
		next = Math.floor(Math.random() * PHRASES.length);
	}
	return next;
}

onMounted(() => {
	// Start on a random phrase so successive turns don't always open the same.
	idx = Math.floor(Math.random() * PHRASES.length);
	phrase.value = PHRASES[idx];
	timer = setInterval(() => {
		idx = pickDifferent();
		phrase.value = PHRASES[idx];
	}, ROTATE_MS);
});

onUnmounted(() => {
	// Stop immediately when the panel drops isTyping (v-if unmounts us).
	if (timer) {
		clearInterval(timer);
		timer = null;
	}
});
</script>

<style scoped>
.ati {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	/* Inherit the host bubble's colour + typography so we look native in every
	   panel and in light/dark, rather than hardcoding a palette. */
	color: inherit;
	font-size: 0.92em;
	font-style: italic;
	opacity: 0.85;
	white-space: nowrap;
}

.ati-pulse {
	flex: 0 0 auto;
	width: 7px;
	height: 7px;
	border-radius: 50%;
	background: currentColor;
	animation: ati-pulse 1.4s ease-in-out infinite;
}

@keyframes ati-pulse {
	0%, 100% { transform: scale(0.7); opacity: 0.35; }
	50%      { transform: scale(1);   opacity: 0.8;  }
}

/* Fade one word out and the next in, synced to the actual swap. */
.ati-swap-enter-active,
.ati-swap-leave-active { transition: opacity 0.22s ease; }
.ati-swap-enter-from,
.ati-swap-leave-to { opacity: 0; }

/* Reduced motion: text still rotates (JS-driven), but no pulse or fade —
   parity-or-better vs the old bouncing dots. */
@media (prefers-reduced-motion: reduce) {
	.ati-pulse { animation: none; opacity: 0.6; }
	.ati-swap-enter-active,
	.ati-swap-leave-active { transition: none; }
}
</style>
