<template>
	<CardShell :title="title">
		<Stack :gap="12">
			<Stack v-for="(c, i) in value.cases" :key="i" :gap="4" class="tc-case">
				<Heading :text="c.scenario || `Check ${i + 1}`" />
				<TextBlock v-if="c.when" class="tc-line"><span class="tc-label">When</span>{{ c.when }}</TextBlock>
				<TextBlock v-if="c.expected" class="tc-line"><span class="tc-label">Expect</span>{{ c.expected }}</TextBlock>
				<Row :gap="8" class="tc-run-row">
					<ActionButton
						v-if="canApply"
						:label="results[i] && results[i].loading ? 'Running…' : 'Run this check'"
						kind="outline"
						:disabled="busy || (results[i] && results[i].loading)"
						@press="run(i)"
					/>
					<span
						v-if="results[i] && !results[i].loading"
						class="tc-chip"
						:class="results[i].passed ? 'tc-chip--pass' : 'tc-chip--fail'"
					>
						{{ results[i].passed ? "✓ Passed" : "✗ Failed" }}
					</span>
					<TextBlock v-if="results[i] && !results[i].loading && results[i].summary" class="tc-result">
						{{ results[i].summary }}
					</TextBlock>
				</Row>
			</Stack>
		</Stack>
	</CardShell>
</template>
<script setup>
// TestCaseCard (WI-001673 primitives) = CardShell[Stack[Heading, TextBlock,
// Row[ActionButton, result]]]. Renders onefm.test_cases — the plain-English
// checks that rode the legacy Logix tests_checklist payload. Run reaches
// run_logix_test_case through the HOST (action "run-test"): the host owns
// which script is linked and hands the pass/fail result back through the
// payload's onResult callback — the card never calls the API itself.
import { computed, reactive } from "vue";
import ActionButton from "../primitives/ActionButton.vue";
import CardShell from "../primitives/CardShell.vue";
import Heading from "../primitives/Heading.vue";
import Row from "../primitives/Row.vue";
import Stack from "../primitives/Stack.vue";
import TextBlock from "../primitives/TextBlock.vue";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
	// Apply-capability handshake: false = this host has no test runner
	// (it owns no linked script), so the checklist is read-only.
	canApply: { type: Boolean, default: true },
});
const emit = defineEmits(["action"]);

const title = computed(() => props.value.summary || "Test checklist");
const results = reactive({}); // case index → { loading, passed, summary }

function run(i) {
	results[i] = { loading: true, passed: null, summary: "" };
	emit("action", "run-test", {
		index: i,
		inputs: props.value.cases[i].inputs || {},
		onResult: (res) => {
			results[i] = {
				loading: false,
				passed: !!(res && res.passed),
				summary: (res && res.summary) || "",
			};
		},
	});
}
</script>
<style scoped>
.tc-case { border: 1px solid #ededed; border-radius: 8px; padding: 8px 10px; }
.tc-label { display: inline-block; min-width: 46px; margin-right: 6px; font-size: 10px;
	font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #7c7c7c; }
.tc-run-row { margin-top: 4px; }
.tc-chip { display: inline-flex; align-items: center; height: 20px; padding: 0 8px;
	border-radius: 99px; font-size: 12px; font-weight: 600; }
.tc-chip--pass { background: #e8f5e9; color: #278f5e; }
.tc-chip--fail { background: #fdecec; color: #cc2929; }
.tc-result { font-size: 12px; color: #525252; flex: 1; }
:global([data-theme="dark"]) .tc-case { border-color: #343434; }
:global([data-theme="dark"]) .tc-label { color: #808080; }
:global([data-theme="dark"]) .tc-chip--pass { background: #143c2a; color: #58c08e; }
:global([data-theme="dark"]) .tc-chip--fail { background: #46181c; color: #fc7474; }
:global([data-theme="dark"]) .tc-result { color: #999; }
</style>
