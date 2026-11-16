<template>
	<header class="bg-white border-b px-4 sm:px-6 py-4">
		<router-link to="/processa/evals" class="text-xs text-gray-500 hover:underline"
			>← Evals</router-link
		>
		<div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 mt-1">
			<div class="min-w-0">
				<div class="flex flex-wrap items-center gap-2">
					<h1 class="text-xl font-semibold text-gray-900">
						{{ suite.title || suiteName }}
					</h1>
					<span
						v-if="suite.eval_type"
						class="text-xs px-2 py-0.5 rounded-full"
						:class="
							suite.eval_type === 'Agent'
								? 'bg-indigo-50 text-indigo-700'
								: suite.eval_type === 'Memory'
									? 'bg-teal-50 text-teal-700'
									: 'bg-blue-50 text-blue-700'
						"
					>
						{{ suite.eval_type }} eval
					</span>
				</div>
				<!-- The agent is editable here because this is the screen where a wrong assignment shows up. -->
				<div class="text-xs text-gray-400 flex flex-wrap items-center gap-1">
					<button
						class="underline decoration-dotted underline-offset-2 hover:text-gray-700"
						:title="'Run this suite against a different agent'"
						@click="openReassign"
					>
						{{ suite.agent_name || suite.agent_configuration || "no agent" }}
					</button>
					<span>· {{ suite.process_model || "no process" }}</span>
					<span>·</span>
					<button
						class="text-blue-600 hover:underline"
						title="How many times each case runs, and the pass rate this suite must clear"
						@click="openThresholds"
					>
						{{ suite.pass_k > 1 ? `${suite.pass_k} runs per case` : "1 run per case"
						}}<span v-if="suite.min_pass_rate"
							>, needs {{ suite.min_pass_rate }}%</span
						>
					</button>
					<span>·</span>
					<button
						class="text-blue-600 hover:underline"
						title="Which automated job runs this suite"
						@click="openThresholds"
					>
						{{
							suite.ci_role
								? `runs on ${suite.ci_role.toLowerCase()}`
								: "runs when asked"
						}}
					</button>
					<span v-if="readiness">·</span>
					<button
						v-if="readiness"
						class="text-blue-600 hover:underline"
						:title="
							readiness.minimum
								? `The golden dataset for ${readiness.subject}: ${readiness.cases} case(s), ${readiness.minimum} is the mark`
								: `The golden dataset for ${readiness.subject}: ${readiness.cases} case(s); the agent has set no minimum`
						"
						@click="openDataset"
					>
						dataset {{ readiness.cases
						}}<template v-if="readiness.minimum">/{{ readiness.minimum }}</template>
					</button>
					<span
						v-if="suite.gate_deployment"
						class="inline-block px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700"
						:title="`Deploying ${suite.process_model || 'this suite\'s map'} is refused while this suite is below its minimum`"
						>gates deploy</span
					>
				</div>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<Button icon-left="file-plus" @click="openNewCase">New case</Button>
				<Button icon-left="git-branch" @click="showFromRun = true">From run</Button>
				<Button
					variant="subtle"
					icon-left="play"
					:disabled="!selected.length"
					:loading="runningSelected"
					@click="runSelected"
				>
					Run selected ({{ selected.length }})
				</Button>
				<Button
					variant="subtle"
					icon-left="refresh-cw"
					:disabled="!canRecheck"
					:loading="rechecking"
					:title="
						canRecheck
							? 'Re-evaluate assertions against the last stored answers — no new agent calls'
							: 'Run the suite once before re-checking'
					"
					@click="recheckSuite"
					>Re-check</Button
				>
				<Button
					icon-left="columns"
					:disabled="!cases.length"
					:title="
						cases.length
							? 'Run these cases against a second agent and compare the two side by side'
							: 'Add a case first'
					"
					@click="openCompare"
					>A/B compare</Button
				>
				<Button
					variant="solid"
					icon-left="play"
					:loading="runningSuite"
					@click="runWholeSuite"
					>Run suite</Button
				>
			</div>
		</div>
	</header>
</template>

<script setup>
import { inject } from "vue";
import { Button } from "frappe-ui";
import { EVAL_SUITE_KEY } from "@/composables/Eval/useEvalSuiteState";

const {
	suiteName,
	suite,
	readiness,
	cases,
	selected,
	canRecheck,
	runningSelected,
	rechecking,
	runningSuite,
	showFromRun,
	openReassign,
	openThresholds,
	openDataset,
	openNewCase,
	runSelected,
	recheckSuite,
	openCompare,
	runWholeSuite,
} = inject(EVAL_SUITE_KEY);
</script>
