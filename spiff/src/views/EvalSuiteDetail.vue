<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4">
			<router-link to="/processa/evals" class="text-xs text-gray-500 hover:underline">← Evals</router-link>
			<div class="flex items-center justify-between mt-1">
				<div>
					<div class="flex items-center gap-2">
						<h1 class="text-xl font-semibold text-gray-900">{{ suite.title || suiteName }}</h1>
						<span
							v-if="suite.eval_type"
							class="text-xs px-2 py-0.5 rounded-full"
							:class="suite.eval_type === 'Agent' ? 'bg-indigo-50 text-indigo-700' : 'bg-blue-50 text-blue-700'"
						>
							{{ suite.eval_type }} eval
						</span>
					</div>
					<!-- The agent is editable here, not just on the Evals list. A
					     suite is reassigned far more often than it is created —
					     an adversarial pack is written once and pointed at each
					     agent in turn — and this is the screen you are on when
					     you discover it is aimed at the wrong one. -->
					<div class="text-xs text-gray-400 flex items-center gap-1">
						<button
							v-if="canReassign"
							class="underline decoration-dotted underline-offset-2 hover:text-gray-700"
							:title="'Run this suite against a different agent'"
							@click="openReassign"
						>{{ suite.agent_name || suite.agent_configuration || "no agent" }}</button>
						<span v-else>{{ suite.agent_name || suite.agent_configuration || "no agent" }}</span>
						<span>· {{ suite.process_model || "no process" }}</span>
						<span>·</span>
						<button
							class="text-blue-600 hover:underline"
							title="How many times each case runs, and the pass rate this suite must clear"
							@click="openThresholds"
						>{{ suite.pass_k > 1 ? `${suite.pass_k} runs per case` : "1 run per case" }}<span
							v-if="suite.min_pass_rate"
						>, needs {{ suite.min_pass_rate }}%</span></button>
						<span v-if="readiness">·</span>
						<button
							v-if="readiness"
							class="text-blue-600 hover:underline"
							:title="`The golden dataset for ${readiness.subject}: ${readiness.cases} case(s), ${readiness.minimum} is the mark`"
							@click="openDataset"
						>dataset {{ readiness.cases }}/{{ readiness.minimum }}</button>
						<span
							v-if="suite.gate_deployment"
							class="inline-block px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700"
							:title="`Deploying ${suite.process_model || 'this suite\'s map'} is refused while this suite is below its minimum`"
						>gates deploy</span>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<Button icon-left="file-plus" @click="openNewCase">New case</Button>
					<Button icon-left="git-branch" @click="showFromRun = true">From run</Button>
					<Button variant="subtle" icon-left="play" :disabled="!selected.length" :loading="runningSelected" @click="runSelected">
						Run selected ({{ selected.length }})
					</Button>
					<Button
						variant="subtle"
						icon-left="refresh-cw"
						:disabled="!canRecheck"
						:loading="rechecking"
						:title="canRecheck ? 'Re-evaluate assertions against the last stored answers — no new agent calls' : 'Run the suite once before re-checking'"
						@click="recheckSuite"
					>Re-check</Button>
					<Button
						icon-left="columns"
						:disabled="!cases.length"
						:title="cases.length ? 'Run these cases against a second agent and compare the two side by side' : 'Add a case first'"
						@click="openCompare"
					>A/B compare</Button>
					<Button variant="solid" icon-left="play" :loading="runningSuite" @click="runWholeSuite">Run suite</Button>
				</div>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<div v-if="loadError" class="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3">{{ loadError }}</div>

			<!-- Dashboard -->
			<div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-4">
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-blue-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cases</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.cases ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-indigo-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Runs</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.runs ?? 0 }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4" :class="metrics.latest?.status === 'Passed' ? 'border-green-500' : metrics.latest ? 'border-red-500' : 'border-gray-300'">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Latest run</div>
					<div class="text-base font-bold text-gray-900">
						{{ metrics.latest ? `${metrics.latest.status} · ${metrics.latest.passed}/${metrics.latest.total}` : "—" }}
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Pass rate</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.pass_rate != null ? metrics.pass_rate + "%" : "—" }}</div>
					<svg v-if="sparkPoints" viewBox="0 0 100 20" preserveAspectRatio="none" class="w-full h-5 mt-1">
						<polyline :points="sparkPoints" fill="none" stroke="currentColor" stroke-width="2" class="text-green-500" />
					</svg>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-amber-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Tokens (latest)</div>
					<div class="text-2xl font-bold text-gray-900">{{ fmt(metrics.latest_tokens ?? 0) }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-purple-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Cost (latest)</div>
					<div class="text-2xl font-bold text-gray-900">{{ fmtCost(metrics.latest_cost ?? 0) }}</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-rose-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Pass rate (latest)</div>
					<div class="text-2xl font-bold" :class="rateColour">
						{{ metrics.latest?.executions ? `${round1(metrics.latest.pass_rate)}%` : "—" }}
					</div>
					<div v-if="metrics.latest?.executions" class="text-xs text-gray-500">
						{{ metrics.latest.executions }} execution(s)<span v-if="suite.min_pass_rate">, needs {{ suite.min_pass_rate }}%</span>
					</div>
				</div>
				<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-cyan-500">
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">Assertion coverage</div>
					<div class="text-2xl font-bold text-gray-900">{{ metrics.assertion_coverage?.with_assertions ?? 0 }} / {{ metrics.assertion_coverage?.total ?? 0 }}</div>
				</div>
			</div>

			<!-- Consistency — which cases disagree with themselves over time -->
			<div class="bg-white rounded-lg shadow-sm mb-6">
				<div class="border-b px-6 py-3 flex items-center justify-between">
					<span class="text-sm font-semibold text-gray-700">
						Consistency
						<span class="text-gray-400 font-normal">(last {{ consistency.runs?.length || 0 }} run(s))</span>
					</span>
					<Button variant="subtle" icon-left="activity" :loading="loadingConsistency" @click="loadConsistency">
						{{ consistency.cases ? "Refresh" : "Show" }}
					</Button>
				</div>
				<div v-if="consistency.cases && !consistency.cases.length" class="p-6 text-sm text-gray-500">
					No results recorded yet — run the suite once.
				</div>
				<div v-else-if="consistency.cases" class="p-4">
					<p v-if="!flakyCases.length" class="text-sm text-green-700">
						Every case has agreed with itself across these runs.
					</p>
					<table v-else class="w-full text-sm">
						<thead>
							<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
								<th class="px-3 py-2 font-medium">Case</th>
								<th class="px-3 py-2 font-medium text-right">Consistency</th>
								<th class="px-3 py-2 font-medium">History (oldest → newest)</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="c in flakyCases" :key="c.case" class="border-b border-gray-100">
								<td class="px-3 py-2 font-medium text-gray-900">{{ c.title }}</td>
								<td class="px-3 py-2 text-right" :class="c.consistency_rate < 100 ? 'text-amber-700' : 'text-gray-600'">
									{{ round1(c.consistency_rate) }}%
									<span class="text-xs text-gray-400">({{ c.passes }}/{{ c.executions }})</span>
								</td>
								<td class="px-3 py-2">
									<span
										v-for="h in c.history"
										:key="h.run"
										class="inline-block w-6 h-6 mr-1 rounded text-center text-xs leading-6"
										:class="h.passes === h.runs ? 'bg-green-100 text-green-700' : (h.passes ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700')"
										:title="`${h.run} — ${h.passes}/${h.runs} passed`"
									>{{ h.passes }}/{{ h.runs }}</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- Cases -->
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 text-sm font-semibold text-gray-700">
					Cases <span class="text-gray-400 font-normal">({{ cases.length }})</span>
				</div>
				<div v-if="loading" class="p-6 space-y-3 animate-pulse">
					<div v-for="n in 3" :key="n" class="h-8 bg-gray-100 rounded"></div>
				</div>
				<div v-else-if="!cases.length" class="p-8 text-center text-sm text-gray-500">
					No cases yet — add one with "New case" or "From run".
				</div>
				<table v-else class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
							<th class="px-4 py-3 w-8"><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
							<th class="px-4 py-3 font-medium">Case</th>
							<th class="px-4 py-3 font-medium">Assertions</th>
							<th class="px-4 py-3 font-medium text-right">Actions</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="c in cases" :key="c.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-4 py-3"><input type="checkbox" :value="c.name" v-model="selected" /></td>
							<td class="px-4 py-3">
								<div class="font-medium text-gray-900">{{ c.title }}</div>
								<div v-if="c.source_run" class="text-xs text-gray-400">from run</div>
							</td>
							<td class="px-4 py-3">
								<span v-for="t in c.assertion_types" :key="t" class="inline-block px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600 mr-1">{{ t }}</span>
								<span v-if="!c.assertion_types.length" class="text-xs text-amber-600">no assertions</span>
							</td>
							<td class="px-4 py-3 text-right whitespace-nowrap">
								<Button variant="ghost" icon-left="pencil" @click="openEditCase(c)">Edit</Button>
								<Button
									variant="ghost"
									icon-left="refresh-cw"
									:disabled="!canRecheck"
									:loading="recheckingCase[c.name]"
									:title="canRecheck ? 'Re-evaluate this case\'s assertions against its last stored answer' : 'Run this case once before re-checking'"
									@click="recheckCase(c)"
								>Re-check</Button>
								<Button icon-left="play" :loading="runningCase[c.name]" @click="runCase(c)">Run</Button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Runs -->
			<div class="bg-white rounded-lg shadow-sm">
				<div class="border-b px-6 py-3 text-sm font-semibold text-gray-700">Recent runs</div>
				<div v-if="!runs.length" class="p-8 text-center text-sm text-gray-500">No runs yet.</div>
				<table v-else class="w-full text-sm">
					<tbody>
						<tr v-for="r in runs" :key="r.name" class="border-b border-gray-100 hover:bg-gray-50">
							<td class="px-6 py-3">
								<router-link :to="`/processa/evals/run/${encodeURIComponent(r.name)}`" class="text-gray-900 hover:underline">
									{{ r.display_title || r.name }}
								</router-link>
								<!-- Only replay is marked. "live" is the norm and labelling every
								     row would bury the one distinction that changes how the
								     result should be read. -->
								<span
									v-if="r.backend === 'replay'"
									class="ml-2 inline-block px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700"
									title="Assertions were re-checked against each case's stored answer — the agent was not called"
								>replay</span>
							</td>
							<td class="px-6 py-3 text-gray-600" :title="(r.case_names || []).join(', ')">
								{{ r.case_label }}
							</td>
							<td class="px-6 py-3">
								<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="runPill(r.status)">{{ r.status }}</span>
							</td>
							<td class="px-6 py-3 text-gray-600">
								{{ r.passed_cases }}/{{ r.total_cases }} passed
								<span v-if="r.total_executions > r.total_cases" class="text-xs text-gray-400">
									· {{ round1(r.pass_rate) }}% of {{ r.total_executions }}
								</span>
							</td>
							<td class="px-6 py-3 text-gray-400 text-xs">{{ r.started_at }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</main>

		<!-- How many times each case runs, and the bar the suite must clear -->
		<Dialog v-model="showThresholds" :options="{ title: 'Runs, pass rate and the deploy gate' }">
			<template #body-content>
				<div class="space-y-3">
					<FormControl
						type="number"
						label="Runs per case"
						v-model="thresholdForm.pass_k"
						description="Above 1, a case passes only when every one of its runs passes. Every run is a billed model call."
					/>
					<FormControl
						type="number"
						label="Minimum pass rate (%)"
						v-model="thresholdForm.min_pass_rate"
						description="The share of executions that must pass. Above 0, activating this suite's map is refused below it."
					/>
					<label class="flex items-start gap-2 text-sm text-gray-700">
						<input type="checkbox" v-model="thresholdForm.gate_deployment" class="mt-1" />
						<span>
							<span class="font-medium">Block deployment below the rate</span>
							<span class="block text-xs text-gray-500">
								Deploying {{ suite.process_model || "this suite's map" }} is refused while this
								suite is under its minimum. With the minimum at 0 it only warns.
							</span>
						</span>
					</label>
					<p v-if="thresholdError" class="text-sm text-red-600">{{ thresholdError }}</p>
					<p v-if="thresholdForm.gate_deployment && !suite.process_model" class="text-sm text-amber-600">
						This suite names no process map, so there is nothing for the gate to block.
					</p>
					<p v-if="Number(thresholdForm.pass_k) > 1 && cases.length" class="text-xs text-gray-500">
						{{ cases.length }} case(s) × {{ thresholdForm.pass_k }} = {{ cases.length * Number(thresholdForm.pass_k) }}
						executions per run of this suite.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingThresholds" @click="saveThresholds">Save</Button>
			</template>
		</Dialog>

		<!-- The golden dataset this suite's agent carries -->
		<Dialog v-model="showDataset" :options="{ title: 'Golden dataset', size: '2xl' }">
			<template #body-content>
				<div v-if="readiness" class="space-y-4">
					<p class="text-sm text-gray-700">
						<span class="font-medium">{{ readiness.subject }}</span> carries
						<span class="font-medium">{{ readiness.cases }}</span> case(s).
						<span v-if="readiness.short_by">{{ readiness.short_by }} short of {{ readiness.minimum }};</span>
						<span v-else>Past the {{ readiness.minimum }} mark;</span>
						{{ readiness.target }} is comfortable.
					</p>
					<p class="text-xs text-gray-500">
						A reading, not a gate. The one hard case-count bar is a skill graduating to Action-Allowed.
					</p>

					<div class="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
						<div v-for="(count, type) in readiness.by_type" :key="type" class="flex justify-between">
							<span :class="count ? 'text-gray-700' : 'text-gray-400'">{{ type }}</span>
							<span :class="count ? 'font-medium' : 'text-gray-400'">{{ count }}</span>
						</div>
					</div>

					<p v-if="readiness.missing_types.length" class="text-sm text-amber-600">
						Nothing yet for: {{ readiness.missing_types.join(", ") }}.
					</p>

					<div class="border-t border-gray-100 pt-3 text-sm">
						<p v-if="readiness.latest_version">
							Latest version <span class="font-medium">v{{ readiness.latest_version.version }}</span>,
							{{ readiness.latest_version.case_count }} case(s), taken
							{{ readiness.latest_version.taken_at }}.
							<span v-if="readiness.drifted_from_version" class="text-amber-600">
								The cases have changed since — take a new version to record where they are now.
							</span>
						</p>
						<p v-else class="text-gray-500">No version taken yet.</p>
					</div>

					<FormControl
						label="Note for this version (optional)"
						v-model="datasetNote"
						description="Why you are recording the dataset here — read later beside the version number."
					/>
					<p v-if="datasetMessage" class="text-sm text-green-700">{{ datasetMessage }}</p>
					<p v-if="datasetError" class="text-sm text-red-600">{{ datasetError }}</p>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button :loading="datasetBusy" @click="downloadDataset">Export</Button>
					<Button variant="solid" :loading="datasetBusy" @click="takeSnapshot">Take version</Button>
				</div>
			</template>
		</Dialog>

		<!-- Case editor modal (new + edit) -->
		<Dialog v-model="showCaseEditor" :options="{ title: caseMode === 'edit' ? 'Edit case' : 'New eval case', size: '3xl' }">
			<template #body-content>
				<div class="space-y-3">
					<div class="text-xs text-gray-500">
						Tests agent: <span class="font-medium text-gray-700">{{ suite.agent_name || suite.agent_configuration || "none" }}</span>
						— its provider, model and system prompt are used.
					</div>
					<FormControl label="Title" v-model="caseForm.title" />
					<div class="grid grid-cols-2 gap-3">
						<FormControl
							type="select"
							label="Case type"
							v-model="caseForm.case_type"
							:options="CASE_TYPE_OPTIONS"
							description="What this case measures."
						/>
						<FormControl
							type="select"
							label="Target skill (optional)"
							v-model="caseForm.target_skill"
							:options="skillOptions"
							description="A skill's golden dataset is the cases pointing at it."
						/>
					</div>
					<p v-if="caseProvenance" class="text-xs text-gray-500">
						Came from {{ caseProvenance }} — that link is set by whatever promoted this case, not here.
					</p>
					<FormControl type="textarea" label="User prompt" v-model="caseForm.input_user_prompt" />
					<FormControl type="textarea" label="Expected output (optional)" v-model="caseForm.expected_output" />

					<!-- Assertions -->
					<div class="border-t pt-3">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold text-gray-700">Assertions</span>
							<Button variant="subtle" icon-left="plus" @click="addAssertion">Add assertion</Button>
						</div>
						<p v-if="!caseForm.assertions.length" class="text-xs text-amber-600 mb-2">
							A case with no assertions passes trivially — add at least one.
						</p>
						<div v-for="(a, i) in caseForm.assertions" :key="i" class="border border-gray-100 rounded-md p-3 mb-2 space-y-2">
							<div class="flex items-center gap-2">
								<FormControl type="select" :options="assertionTypeOptions" v-model="a.assertion_type" class="w-40" />
								<Button variant="ghost" icon-left="trash-2" @click="removeAssertion(i)" />
							</div>
							<FormControl
								v-if="a.assertion_type === 'tool_calls'"
								type="select"
								label="Order mode"
								:options="TOOL_CALL_MODES"
								v-model="a.value"
							/>
							<FormControl
								v-else
								type="textarea"
								:label="VALUE_LABELS[a.assertion_type] || 'Expected value / pattern'"
								v-model="a.value"
							/>
							<div v-if="a.assertion_type === 'llm_judge'" class="grid grid-cols-3 gap-2">
								<FormControl type="select" label="Judge provider" :options="providerOptions" v-model="a.judge_provider" />
								<FormControl type="select" label="Judge model" :options="aiModelOptions" v-model="a.judge_model" />
								<FormControl type="number" label="Pass threshold (1–5)" v-model="a.pass_threshold" />
							</div>
						</div>
					</div>

					<!-- Expected tool calls — what a tool_calls assertion is checked against -->
					<div v-if="wantsToolCalls" class="border-t pt-3">
						<div class="flex items-center justify-between mb-2">
							<span class="text-sm font-semibold text-gray-700">Expected tool calls</span>
							<Button variant="subtle" icon-left="plus" @click="addExpectedCall">Add call</Button>
						</div>
						<p class="text-xs text-gray-500 mb-2">
							One row per thing to check. Rows sharing a Call number describe the same call — give a
							tool and, if the arguments matter, one row per argument. Leave the argument blank to
							require only that the tool ran.
						</p>
						<p v-if="!caseForm.expected_tool_calls.length" class="text-xs text-amber-600 mb-2">
							The tool_calls assertion has nothing to check until you add a call.
						</p>
						<div
							v-for="(e, i) in caseForm.expected_tool_calls"
							:key="i"
							class="flex items-end gap-2 mb-2"
						>
							<FormControl type="number" label="Call" v-model="e.call_order" class="w-16" />
							<FormControl label="Tool" v-model="e.tool_name" class="flex-1" />
							<FormControl label="Argument" v-model="e.argument" class="flex-1" />
							<FormControl type="select" label="Matcher" :options="MATCHER_OPTIONS" v-model="e.matcher" class="w-28" />
							<FormControl label="Expected value" v-model="e.expected_value" class="flex-1" />
							<Button variant="ghost" icon-left="trash-2" @click="removeExpectedCall(i)" />
						</div>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="w-full space-y-2">
					<p v-if="caseError" class="text-sm text-red-600">{{ caseError }}</p>
					<p v-else-if="incompleteAssertion !== -1" class="text-sm text-amber-600">
						Assertion {{ incompleteAssertion + 1 }} needs its
						{{ (VALUE_LABELS[caseForm.assertions[incompleteAssertion].assertion_type] || 'expected value').toLowerCase() }}.
					</p>
					<Button
						variant="solid"
						:loading="savingCase"
						:disabled="!caseForm.title || incompleteAssertion !== -1"
						@click="saveCase"
					>
						{{ caseMode === 'edit' ? 'Save changes' : 'Create case' }}
					</Button>
				</div>
			</template>
		</Dialog>

		<!-- From run modal -->
		<!-- WI-001821: pick a challenger and run the suite twice. The suite's own
		     agent stays bound to the suite throughout — the nominated agent is
		     recorded on the RUN, not on the suite. -->
		<Dialog v-model="showCompare" :options="{ title: 'Compare against another agent' }">
			<template #body-content>
				<div class="space-y-4">
					<p class="text-sm text-gray-600">
						Runs all {{ cases.length }} case{{ cases.length === 1 ? "" : "s" }} twice — once
						against <span class="font-medium">{{ suite.agent_name || suite.agent_configuration || "this suite's agent" }}</span>,
						once against the agent you pick — then shows the two side by side.
						This suite stays assigned to its current agent.
					</p>
					<FormControl
						type="select"
						label="Compare against"
						:options="challengerOptions"
						v-model="challenger"
					/>
					<p v-if="cases.length < 10" class="text-xs text-amber-700 bg-amber-50 rounded p-2">
						{{ cases.length }} case{{ cases.length === 1 ? "" : "s" }} is a small sample — one case
						changing its mind moves the pass rate by {{ Math.round(100 / cases.length) }} points.
						Useful as a signal, not as proof.
					</p>
					<p v-if="compareError" class="text-sm text-red-600">{{ compareError }}</p>
				</div>
			</template>
			<template #actions>
				<Button
					variant="solid"
					:loading="startingCompare"
					:disabled="!challenger"
					@click="startComparison"
				>Run both</Button>
			</template>
		</Dialog>

		<Dialog v-model="showFromRun" :options="{ title: 'Create case from a run' }">
			<template #body-content>
				<div class="space-y-3">
					<p v-if="loadingAgentRuns" class="text-sm text-gray-500">Loading runs…</p>
					<p v-else-if="!agentRuns.length" class="text-sm text-gray-500">
						No runs to build a case from yet — this suite's agent has not run outside
						the eval system.
					</p>
					<FormControl
						v-else
						type="select"
						label="AI Agent Run"
						:options="agentRunOptions"
						v-model="fromRun.run_name"
						@change="onRunPicked"
					/>
					<p v-if="loadingSteps" class="text-xs text-gray-500">Loading steps…</p>
					<FormControl v-if="runSteps.length" type="select" label="Step (optional)" :options="stepOptions" v-model="fromRun.step_name" />
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="savingFromRun" @click="createFromRun">Create case</Button>
			</template>
		</Dialog>
	</div>
		<!-- ── Reassign the suite's agent ──────────────────────────────── -->
		<Dialog
			:modelValue="showReassign"
			:options="{ title: 'Run this suite against', size: 'lg' }"
			@update:modelValue="(v) => { if (!v) showReassign = false }"
		>
			<template #body-content>
				<div class="space-y-4">
					<p class="text-sm text-gray-600">
						Changes which agent this suite's cases are run against. The cases, their
						assertions and every past run stay exactly as they are — a run records the
						agent it used, so the history stays readable after a reassignment.
					</p>
					<FormControl
						type="autocomplete"
						label="Agent"
						:options="reassignOptions"
						:modelValue="reassignAgent"
						@update:modelValue="(v) => (reassignAgent = v?.value ?? v ?? '')"
					/>
					<p class="text-xs text-gray-500">
						Every agent is listed, including Draft and Needs Attention ones — running
						a suite is how an agent earns its way to Live. Choosing "none" detaches
						the suite instead, for a template pack that is copied rather than run.
					</p>
					<ErrorMessage :message="reassignError" />
				</div>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button variant="subtle" @click="showReassign = false">Cancel</Button>
					<Button variant="solid" :loading="savingReassign" @click="doReassign">Save</Button>
				</div>
			</template>
		</Dialog>

</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { frappeRequest, Button, Dialog, ErrorMessage, FormControl } from "frappe-ui"

const route = useRoute()
const router = useRouter()
const suiteName = route.params.suite

const ASSERTION_TYPES = ["contains", "regex", "equals", "schema_valid", "llm_judge", "max_tokens", "no_tool_call", "tool_calls"]
// What `value` means changes with the type, so the field says which.
const VALUE_LABELS = {
	llm_judge: "Rubric",
	max_tokens: "Token ceiling",
	no_tool_call: "Forbidden tool names",
	tool_calls: "Order mode",
}
// tool_calls checks the run's trace against the Expected Tool Calls below; its
// value is only which of the three modes to check in.
const TOOL_CALL_MODES = [
	{ label: "EXACT — these calls, this order, nothing else", value: "EXACT" },
	{ label: "IN_ORDER — these calls in this order, others allowed between", value: "IN_ORDER" },
	{ label: "ANY_ORDER — these calls happened, order not checked", value: "ANY_ORDER" },
]
const MATCHER_OPTIONS = ["equals", "regex", "contains"].map((m) => ({ label: m, value: m }))
const assertionTypeOptions = ASSERTION_TYPES.map((t) => ({ label: t, value: t }))

const loading = ref(true)
const loadError = ref("")
const suite = ref({})
const cases = ref([])
const runs = ref([])
const metrics = ref({})
const selected = ref([])
const runningCase = reactive({})
const runningSelected = ref(false)
const runningSuite = ref(false)

const providerOptions = ref([])
const aiModelOptions = ref([])

const showCaseEditor = ref(false)
const caseMode = ref("new")
const savingCase = ref(false)
const caseError = ref("")
// value carries the whole meaning of an assertion — the rubric for llm_judge,
// the substring for contains — and is mandatory on the doctype. Catch it here so
// the button explains itself instead of the save failing at the server.
const incompleteAssertion = computed(() =>
	caseForm.assertions.findIndex((a) => !(a.value || "").trim())
)

const CASE_TYPE_OPTIONS = [
	"Output", "Trajectory", "Trigger Positive", "Trigger Negative",
	"Adversarial", "Co-Load Budget", "Memory",
].map((t) => ({ label: t, value: t }))

const skillOptions = ref([{ label: "— none —", value: "" }])

const showDataset = ref(false)
const readiness = ref(null)
const datasetNote = ref("")
const datasetBusy = ref(false)
const datasetMessage = ref("")
const datasetError = ref("")

// Read as soon as the suite loads so the count is visible without opening
// anything. Best-effort: a suite with no agent has no dataset, and that must
// not blank the page.
async function loadReadiness() {
	if (!suite.value.agent_configuration) {
		readiness.value = null
		return
	}
	try {
		readiness.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.golden_dataset.dataset_readiness",
			method: "GET",
			params: { agent: suite.value.agent_configuration },
		})
	} catch (e) {
		readiness.value = null
	}
}

async function loadSkills() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "GET",
			params: { doctype: "AI Skill", fields: JSON.stringify(["name"]), limit_page_length: 0 },
		})
		skillOptions.value = [{ label: "— none —", value: "" }].concat(
			(res || []).map((sk) => ({ label: sk.name, value: sk.name }))
		)
	} catch (e) {
		skillOptions.value = [{ label: "— none —", value: "" }]
	}
}

function openDataset() {
	datasetMessage.value = ""
	datasetError.value = ""
	datasetNote.value = ""
	showDataset.value = true
	loadReadiness()
}

async function takeSnapshot() {
	datasetBusy.value = true
	datasetMessage.value = ""
	datasetError.value = ""
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.golden_dataset.snapshot_dataset",
			method: "POST",
			params: { agent: suite.value.agent_configuration, notes: datasetNote.value },
		})
		datasetMessage.value = `Recorded ${res.label} — ${res.case_count} case(s).`
		await loadReadiness()
	} catch (e) {
		datasetError.value = e.messages?.[0] || e.message || "Could not take a version."
	} finally {
		datasetBusy.value = false
	}
}

async function downloadDataset() {
	datasetBusy.value = true
	datasetError.value = ""
	try {
		const payload = await frappeRequest({
			url: "/api/method/one_bpmn.api.golden_dataset.export_dataset",
			method: "GET",
			params: { agent: suite.value.agent_configuration },
		})
		const blob = new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" })
		const link = document.createElement("a")
		link.href = URL.createObjectURL(blob)
		link.download = `${payload.subject}-golden-dataset.json`.replace(/\s+/g, "-").toLowerCase()
		link.click()
		URL.revokeObjectURL(link.href)
		datasetMessage.value = `Exported ${payload.case_count} case(s).`
	} catch (e) {
		datasetError.value = e.messages?.[0] || e.message || "Could not export."
	} finally {
		datasetBusy.value = false
	}
}

const caseProvenance = computed(() => {
	const from = []
	if (caseForm.source_feedback) from.push(`feedback ${caseForm.source_feedback}`)
	if (caseForm.source_security_event) from.push(`security event ${caseForm.source_security_event}`)
	if (caseForm.source_run) from.push(`run ${caseForm.source_run}`)
	return from.join(", ")
})

const caseForm = reactive({
	name: "", title: "", input_user_prompt: "", expected_output: "", assertions: [],
	case_type: "Output", target_skill: "", source_feedback: "", source_security_event: "", source_run: "",
	expected_tool_calls: [],
})

const showFromRun = ref(false)
const loadingSteps = ref(false)
const savingFromRun = ref(false)
const runSteps = ref([])
const fromRun = reactive({ run_name: "", step_name: "" })

// Candidate AI Agent Runs for the "From run" picker. Distinct from `runs`
// above, which is this suite's own EVAL runs.
const agentRuns = ref([])
const loadingAgentRuns = ref(false)

// Re-check (replay) re-evaluates assertions against each case's last stored
// answer instead of calling the agent again — what you want after editing an
// assertion. It needs a prior result to read, so it is offered only once the
// suite has been run at least once.
const rechecking = ref(false)
const recheckingCase = reactive({})
const canRecheck = computed(() => runs.value.length > 0)

const _fmt = new Intl.NumberFormat("en-US")
const _fmtCost = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 })
function fmt(n) { return _fmt.format(n || 0) }
function fmtCost(n) { return _fmtCost.format(n || 0) }

const allSelected = computed(() => cases.value.length > 0 && selected.value.length === cases.value.length)
const stepOptions = computed(() =>
	[{ label: "(whole run)", value: "" }].concat(runSteps.value.map((s) => ({ label: s.label || s.name, value: s.name })))
)
// "2 Aug, 15:29 · Notify Assignee · Success" — when it ran, what produced it,
// and whether it worked. Enough to tell two runs apart without a second column.
const agentRunOptions = computed(() =>
	[{ label: "Select a run…", value: "" }].concat(
		agentRuns.value.map((r) => ({
			label: `${r.when} · ${r.source} · ${r.status}`,
			value: r.name,
		}))
	)
)
const sparkPoints = computed(() => {
	const s = metrics.value.sparkline
	if (!s || s.length < 2) return null
	const step = 100 / (s.length - 1)
	return s.map((v, i) => `${(i * step).toFixed(1)},${(20 - (v / 100) * 20).toFixed(1)}`).join(" ")
})

function runPill(status) {
	if (status === "Passed") return "bg-green-50 text-green-700"
	if (status === "Failed" || status === "Error") return "bg-red-50 text-red-700"
	if (status === "Running") return "bg-yellow-50 text-yellow-700 animate-pulse"
	return "bg-gray-100 text-gray-500"
}

function toggleAll(e) {
	selected.value = e.target.checked ? cases.value.map((c) => c.name) : []
}

// Frappe puts the useful text in _server_messages / exception; e.message is
// often just "<endpoint> PermissionError", which tells the user nothing.
function errorText(e, fallback) {
	const raw = e?.messages?.length ? e.messages.join(" ") : ""
	const exc = e?.exc_type && e?._error_message ? e._error_message : ""
	return raw || exc || e?.message || fallback
}

async function fetchDetail(silent = false) {
	if (!silent) loading.value = true
	loadError.value = ""
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_suite_detail",
			method: "GET",
			params: { suite: suiteName },
		})
		suite.value = res?.suite || {}
		cases.value = res?.cases || []
		runs.value = res?.runs || []
		metrics.value = res?.metrics || {}
		// Already-open report: a new run makes it stale the moment it lands.
		if (consistency.value.cases) loadConsistency()
		loadReadiness()
	} catch (e) {
		console.error("Failed to load suite:", e)
		if (!silent) loadError.value = errorText(e, "Failed to load this suite.")
	} finally {
		if (!silent) loading.value = false
	}
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

// Poll quietly (no skeleton flicker) until the run leaves "Running".
async function pollRun(runName) {
	for (let i = 0; i < 40; i++) {
		await sleep(1500)
		await fetchDetail(true)
		const r = runs.value.find((x) => x.name === runName)
		if (!r || r.status !== "Running") break
	}
}

async function fetchProviders() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "GET",
			params: { doctype: "AI Provider", fields: JSON.stringify(["name"]), limit_page_length: 0 },
		})
		providerOptions.value = (res || []).map((p) => ({ label: p.name, value: p.name }))
	} catch (e) {
		providerOptions.value = []
	}
}

async function fetchAiModels() {
	try {
		const res = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			method: "GET",
			params: { doctype: "AI Model", fields: JSON.stringify(["name"]), limit_page_length: 0 },
		})
		aiModelOptions.value = (res || []).map((m) => ({ label: m.name, value: m.name }))
	} catch (e) {
		aiModelOptions.value = []
	}
}

function optimisticRun(runName, totalCases) {
	// Show the run immediately so there's no dead time after the click.
	runs.value.unshift({
		name: runName, display_title: "Run — starting…", status: "Running",
		passed_cases: 0, total_cases: totalCases, started_at: "",
	})
}

async function runCases(caseNames, flag, backend = "live") {
	flag.value = true
	loadError.value = ""
	try {
		const runName = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: {
				suite_name: suiteName,
				case_names: caseNames ? JSON.stringify(caseNames) : null,
				backend,
			},
		})
		optimisticRun(runName, caseNames ? caseNames.length : cases.value.length)
		pollRun(runName)
	} catch (e) {
		console.error("Run failed:", e)
		loadError.value = errorText(e, "Failed to start the run.")
	} finally {
		flag.value = false
	}
}

watch(showFromRun, (open) => {
	if (open) loadAgentRuns()
})

// ── A/B comparison (WI-001821) ───────────────────────────────────────────────
const showCompare = ref(false)
const challenger = ref("")
const challengerOptions = ref([])
const startingCompare = ref(false)
const compareError = ref("")

async function openCompare() {
	compareError.value = ""
	challenger.value = ""
	showCompare.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.list_assignable_agents",
			method: "GET",
			// Draft and Needs Attention agents included: evaluating an agent is
			// how it stops being a Draft. The endpoint defaults to Live-only so
			// other callers are untouched.
			params: { include_all: 1 },
		})
		// The suite's own agent is side A, so offering it as the challenger would
		// only produce the "both sides are the same agent" refusal.
		challengerOptions.value = (res || [])
			.filter((a) => a.name !== suite.value.agent_configuration)
			.map((a) => ({ label: agentLabel(a), value: a.name }))
	} catch (e) {
		challengerOptions.value = []
		compareError.value = errorText(e, "Couldn't load the list of agents.")
	}
}

// Every agent is offered, not just the Live ones — evaluating an agent is how
// it stops being a Draft, and one in Needs Attention is precisely the one
// somebody wants to test. The state rides in the label so the choice is
// informed rather than quietly filtered.
function agentLabel(a) {
	const name = a.agent_name || a.name
	const bits = []
	if (a.lifecycle_status && a.lifecycle_status !== "Live") bits.push(a.lifecycle_status)
	if (a.enabled === 0) bits.push("disabled")
	return bits.length ? `${name} — ${bits.join(", ")}` : name
}

// ── Reassigning the suite's agent ─────────────────────────────────────────
// The endpoint already existed and the Evals LIST already used it; the detail
// screen — the one you are on when you notice the suite is aimed at the wrong
// agent — did not offer it.
const showReassign = ref(false)
const reassignAgent = ref("")
const reassignOptions = ref([])
const reassignError = ref("")
const savingReassign = ref(false)

// get_suite_detail does not report an edit right, and reassign_suite enforces
// write permission itself. Rather than invent a second, guessable rule here that
// could disagree with the server's, the control is offered and a refusal comes
// back as the dialog's error — which names the real reason instead of a button
// that is mysteriously missing.
const canReassign = computed(() => true)

async function openReassign() {
	reassignError.value = ""
	reassignAgent.value = suite.value.agent_configuration || ""
	showReassign.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.list_assignable_agents",
			method: "GET",
			// Draft and Needs Attention agents included: evaluating an agent is
			// how it stops being a Draft. The endpoint defaults to Live-only so
			// other callers are untouched.
			params: { include_all: 1 },
		})
		// Detaching is offered here as well as on the Evals list. It is a real
		// thing to want — a template pack that is copied rather than run — and
		// the endpoint has always supported it. Named for what it does rather
		// than shown as an empty row, so landing on it is a choice.
		reassignOptions.value = [
			{ label: "— none (detach this suite) —", value: "" },
			...(res || []).map((a) => ({ label: agentLabel(a), value: a.name })),
		]
	} catch (e) {
		reassignOptions.value = []
		reassignError.value = errorText(e, "Couldn't load the list of agents.")
	}
}

async function doReassign() {
	savingReassign.value = true
	reassignError.value = ""
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.reassign_suite",
			method: "POST",
			params: { suite: suiteName, agent_configuration: reassignAgent.value || null },
		})
		showReassign.value = false
		// Reload rather than patching the local copy: the header also shows the
		// agent's display NAME, which only the server can resolve.
		await fetchDetail()
	} catch (e) {
		reassignError.value = errorText(e, "Couldn't reassign the suite.")
	} finally {
		savingReassign.value = false
	}
}

async function startComparison() {
	startingCompare.value = true
	compareError.value = ""
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_comparison",
			method: "POST",
			params: { suite_name: suiteName, agent_b: challenger.value },
		})
		showCompare.value = false
		// Both runs are queued, not finished — the comparison page opens on a
		// pair that is still running and says so, rather than making the user
		// watch a spinner here and then find the page themselves.
		router.push(
			`/processa/evals/compare/${encodeURIComponent(res.run_a)}/${encodeURIComponent(res.run_b)}`
		)
	} catch (e) {
		compareError.value = errorText(e, "Couldn't start the comparison.")
	} finally {
		startingCompare.value = false
	}
}

function runWholeSuite() { return runCases(null, runningSuite) }
function runSelected() { return runCases(selected.value, runningSelected) }

// Re-check = the replay backend: no new agent call, assertions re-evaluated
// against each case's last stored answer.
function recheckSuite() { return runCases(null, rechecking, "replay") }
async function recheckCase(c) {
	recheckingCase[c.name] = true
	try {
		await runCases([c.name], { value: false }, "replay")
	} finally {
		recheckingCase[c.name] = false
	}
}
async function runCase(c) {
	runningCase[c.name] = true
	try {
		const runName = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_runner.run_eval_cases",
			method: "POST",
			params: { suite_name: suiteName, case_names: JSON.stringify([c.name]) },
		})
		optimisticRun(runName, 1)
		pollRun(runName)
	} catch (e) {
		console.error("Run failed:", e)
		loadError.value = errorText(e, "Failed to start the run.")
	} finally {
		runningCase[c.name] = false
	}
}

// ── Runs per case / minimum pass rate ───────────────────────────────────
const showThresholds = ref(false)
const savingThresholds = ref(false)
const thresholdError = ref("")
const thresholdForm = reactive({ pass_k: 1, min_pass_rate: 0, gate_deployment: false })

function openThresholds() {
	thresholdForm.pass_k = suite.value.pass_k || 1
	thresholdForm.min_pass_rate = suite.value.min_pass_rate || 0
	thresholdForm.gate_deployment = !!suite.value.gate_deployment
	thresholdError.value = ""
	showThresholds.value = true
}
async function saveThresholds() {
	savingThresholds.value = true
	thresholdError.value = ""
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.update_suite_thresholds",
			method: "POST",
			params: {
				suite: suiteName,
				pass_k: thresholdForm.pass_k,
				min_pass_rate: thresholdForm.min_pass_rate,
				gate_deployment: thresholdForm.gate_deployment ? 1 : 0,
			},
		})
		showThresholds.value = false
		await fetchDetail()
	} catch (e) {
		thresholdError.value = errorText(e, "Could not save.")
	} finally {
		savingThresholds.value = false
	}
}

// ── Consistency over time ───────────────────────────────────────────────
const consistency = ref({})
const loadingConsistency = ref(false)
// The report exists for the cases that disagree with themselves; a solid case
// is not news.
const flakyCases = computed(() =>
	(consistency.value.cases || []).filter((c) => c.consistency_rate < 100 || c.flips)
)
const rateColour = computed(() => {
	const m = metrics.value?.latest
	if (!m?.executions) return "text-gray-900"
	if (suite.value.min_pass_rate && m.pass_rate < suite.value.min_pass_rate) return "text-red-600"
	return m.pass_rate === 100 ? "text-green-700" : "text-amber-600"
})
function round1(n) {
	return Math.round((Number(n) || 0) * 10) / 10
}
async function loadConsistency() {
	loadingConsistency.value = true
	try {
		consistency.value = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.case_consistency",
			method: "GET",
			params: { suite: suiteName },
		})
	} catch (e) {
		console.error("Failed to load the consistency report:", e)
	} finally {
		loadingConsistency.value = false
	}
}

// ── Case editor (new + edit) ─────────────────────────────────────────────
function resetCaseForm() {
	Object.assign(caseForm, {
		name: "", title: "", input_user_prompt: "", expected_output: "",
		case_type: "Output", target_skill: "", source_feedback: "", source_security_event: "", source_run: "",
		assertions: [], expected_tool_calls: [],
	})
}
// The grid is only worth showing when something checks it.
const wantsToolCalls = computed(() =>
	caseForm.assertions.some((a) => a.assertion_type === "tool_calls")
)
function addExpectedCall() {
	const next = caseForm.expected_tool_calls.length
		? Math.max(...caseForm.expected_tool_calls.map((e) => Number(e.call_order) || 0)) + 1
		: 1
	caseForm.expected_tool_calls.push({ call_order: next, tool_name: "", argument: "", matcher: "equals", expected_value: "" })
}
function removeExpectedCall(i) {
	caseForm.expected_tool_calls.splice(i, 1)
}
function addAssertion() {
	caseForm.assertions.push({ assertion_type: "contains", value: "", judge_provider: "", judge_model: "", pass_threshold: 4 })
}
function removeAssertion(i) {
	caseForm.assertions.splice(i, 1)
}
function openNewCase() {
	resetCaseForm()
	caseMode.value = "new"
	caseError.value = ""
	showCaseEditor.value = true
}
async function openEditCase(c) {
	caseMode.value = "edit"
	resetCaseForm()
	caseError.value = ""
	showCaseEditor.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.get_eval_case",
			method: "GET",
			params: { name: c.name },
		})
		Object.assign(caseForm, {
			name: res.name, title: res.title,
			input_user_prompt: res.input_user_prompt || "",
			expected_output: res.expected_output || "",
			case_type: res.case_type || "Output",
			target_skill: res.target_skill || "",
			source_feedback: res.source_feedback || "",
			source_security_event: res.source_security_event || "",
			source_run: res.source_run || "",
			assertions: (res.assertions || []).map((a) => ({
				assertion_type: a.assertion_type, value: a.value || "",
				judge_provider: a.judge_provider || "", judge_model: a.judge_model || "",
				pass_threshold: a.pass_threshold ?? 4,
			})),
			expected_tool_calls: (res.expected_tool_calls || []).map((e) => ({
				call_order: e.call_order || 1, tool_name: e.tool_name || "",
				argument: e.argument || "", matcher: e.matcher || "equals",
				expected_value: e.expected_value || "",
			})),
		})
	} catch (e) {
		console.error("Failed to load case:", e)
	}
}
async function saveCase() {
	savingCase.value = true
	caseError.value = ""
	try {
		const payload = {
			title: caseForm.title, input_user_prompt: caseForm.input_user_prompt,
			expected_output: caseForm.expected_output, assertions: JSON.stringify(caseForm.assertions),
			case_type: caseForm.case_type, target_skill: caseForm.target_skill,
			expected_tool_calls: JSON.stringify(caseForm.expected_tool_calls),
		}
		if (caseMode.value === "edit") {
			await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.update_eval_case", method: "POST", params: { name: caseForm.name, ...payload } })
		} else {
			await frappeRequest({ url: "/api/method/one_bpmn.api.eval_api.create_eval_case", method: "POST", params: { suite: suiteName, ...payload } })
		}
		showCaseEditor.value = false
		fetchDetail()
	} catch (e) {
		// Previously console.error only, so a rejected save looked like a dead
		// button: the dialog stayed open with no explanation and the reason was
		// only visible with devtools open.
		console.error("Save case failed:", e)
		caseError.value = serverMessage(e) || "Could not save the case."
	} finally {
		savingCase.value = false
	}
}

// Frappe puts the useful text in _server_messages (a JSON array of JSON
// strings); e.message is the bare exception class for a 417.
function serverMessage(e) {
	const raw = e?._server_messages || e?.exc || ""
	try {
		const parsed = JSON.parse(raw)
		const first = Array.isArray(parsed) ? parsed[0] : parsed
		const inner = typeof first === "string" ? JSON.parse(first) : first
		return (inner?.message || "").replace(/<[^>]*>/g, "").trim()
	} catch {
		return (e?.message || "").trim()
	}
}

async function loadAgentRuns() {
	loadingAgentRuns.value = true
	agentRuns.value = []
	try {
		agentRuns.value = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.list_runs_for_case_picker",
			method: "GET",
			params: { suite: suiteName },
		}) || []
	} catch (e) {
		console.error("Loading runs failed:", e)
		agentRuns.value = []
	} finally {
		loadingAgentRuns.value = false
	}
}

// Picking a run immediately offers its steps — the old dialog made you press
// "Load steps" as a separate action, which only ever had one sensible moment.
function onRunPicked() {
	fromRun.step_name = ""
	runSteps.value = []
	if (fromRun.run_name) loadSteps()
}

async function loadSteps() {
	loadingSteps.value = true
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.get_run_steps_for_case_picker",
			method: "GET",
			params: { run_name: fromRun.run_name },
		})
		runSteps.value = res || []
	} catch (e) {
		runSteps.value = []
	} finally {
		loadingSteps.value = false
	}
}

async function createFromRun() {
	savingFromRun.value = true
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			method: "POST",
			params: { run_name: fromRun.run_name, step_name: fromRun.step_name || null, suite: suiteName },
		})
		showFromRun.value = false
		fromRun.run_name = ""
		fromRun.step_name = ""
		runSteps.value = []
		fetchDetail()
	} catch (e) {
		console.error("Create from run failed:", e)
	} finally {
		savingFromRun.value = false
	}
}

onMounted(async () => {
	await fetchDetail()
	fetchProviders()
	fetchAiModels()
	loadSkills()

	// Arriving with ?case=<name> opens that case straight into the editor.
	// Converting a complaint in the Feedback queue lands here, and the next
	// thing the reviewer has to do is write what SHOULD have happened — so the
	// editor is the destination, not the suite's case list with the new row
	// somewhere in it.
	const wanted = route.query.case
	if (wanted) {
		const found = (cases.value || []).find((c) => c.name === wanted)
		if (found) openEditCase(found)
		else openEditCase({ name: wanted })
	}
})
</script>
