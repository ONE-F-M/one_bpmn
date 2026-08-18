<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Security</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						Every screening verdict, the rules behind them, and the conversations they froze.
					</p>
				</div>
				<nav class="flex gap-1 bg-gray-100 rounded-lg p-1">
					<button
						v-for="t in tabs"
						:key="t.key"
						class="px-3 py-1.5 text-sm rounded-md transition-colors"
						:class="tab === t.key ? 'bg-white shadow-sm font-medium text-gray-900' : 'text-gray-600 hover:text-gray-900'"
						@click="tab = t.key"
					>
						{{ t.label }}
						<span v-if="t.count !== null" class="ml-1 text-xs text-gray-400">{{ t.count }}</span>
					</button>
				</nav>
			</div>
		</header>

		<!-- Toolbar / Filters — same shape as the Instances toolbar: a flush bar
		     under the header, frappe-ui controls, and no labels stacked above.
		     Each control's first option names the filter, so the row reads as one
		     line of pills instead of four little labelled boxes. -->
		<div
			v-show="tab === 'events'"
			class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center"
		>
			<FormControl
				type="select"
				v-model="filters.agent"
				:options="agentOptions"
				class="w-56"
				@change="loadEvents(0)"
			/>
			<FormControl
				type="select"
				v-model="filters.boundary"
				:options="boundaryOptions"
				class="w-44"
				@change="loadEvents(0)"
			/>
			<FormControl
				type="select"
				v-model="filters.action"
				:options="actionOptions"
				class="w-44"
				@change="loadEvents(0)"
			/>
			<!-- Searches on Enter rather than on every keystroke: this one hits the
			     database with a LIKE across three columns. -->
			<FormControl
				type="text"
				v-model="filters.search"
				placeholder="Search rule, classifier or detail…"
				class="w-72"
				@keyup.enter="loadEvents(0)"
			/>
			<Button v-if="anyFilter" variant="ghost" @click="resetFilters">
				Clear filters
			</Button>

			<!-- Page size, right-aligned like the Instances toolbar. This log grows
			     without bound, so how much of it to pull at once is the reviewer's
			     call rather than a fixed 50. -->
			<div class="flex items-center gap-2 ml-auto">
				<span class="text-sm text-gray-600 whitespace-nowrap">Page Size:</span>
				<FormControl
					type="select"
					v-model="pageLength"
					:options="PAGE_SIZES"
					class="w-20"
					@change="changePageSize"
				/>
			</div>
		</div>

		<main class="flex-1 overflow-auto p-6">
			<!-- ── Events ─────────────────────────────────────────────────── -->
			<section v-show="tab === 'events'" class="space-y-4">
				<div class="bg-white rounded-lg shadow-sm overflow-hidden">
					<div v-if="loading.events" class="p-6 text-sm text-gray-500">Loading events…</div>
					<div v-else-if="!events.length" class="p-6 text-sm text-gray-500">
						No events match these filters.
						<span v-if="total === 0 && !anyFilter">
							Nothing has been screened yet — events appear here as agents are used.
						</span>
					</div>
					<table v-else class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
							<tr>
								<th class="text-left px-4 py-2 font-medium">When</th>
								<th class="text-left px-4 py-2 font-medium">Agent</th>
								<th class="text-left px-4 py-2 font-medium">Stage</th>
								<th class="text-left px-4 py-2 font-medium">Boundary</th>
								<th class="text-left px-4 py-2 font-medium">Action</th>
								<th class="text-left px-4 py-2 font-medium">Detail</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="e in events"
								:key="e.name"
								class="border-t hover:bg-gray-50 cursor-pointer"
								@click="openEvent(e.name)"
							>
								<td class="px-4 py-2 whitespace-nowrap text-gray-500">{{ shortTime(e.creation) }}</td>
								<td class="px-4 py-2">{{ e.agent_configuration || "—" }}</td>
								<td class="px-4 py-2">{{ e.stage }}</td>
								<td class="px-4 py-2 text-gray-500">{{ e.boundary }}</td>
								<td class="px-4 py-2">
									<span class="text-xs px-2 py-0.5 rounded-full" :class="actionClass(e.action)">{{ e.action }}</span>
									<span v-if="e.severity" class="ml-1 text-xs text-gray-400">{{ e.severity }}</span>
								</td>
								<td class="px-4 py-2 text-gray-600 truncate max-w-md">{{ e.detail || "—" }}</td>
							</tr>
						</tbody>
					</table>

					<div v-if="events.length" class="flex items-center justify-between border-t px-4 py-2 text-xs text-gray-500">
						<span>Showing {{ start + 1 }}–{{ start + events.length }} of {{ total }}</span>
						<span class="flex gap-2">
							<Button variant="subtle" :disabled="start === 0" @click="loadEvents(start - pageSize)">Previous</Button>
							<Button variant="subtle" :disabled="start + pageSize >= total" @click="loadEvents(start + pageSize)">Next</Button>
						</span>
					</div>
				</div>
			</section>

			<!-- ── Pattern pack ───────────────────────────────────────────── -->
			<section v-show="tab === 'patterns'" class="space-y-4">
				<div class="bg-white rounded-lg shadow-sm p-4 flex items-center justify-between">
					<p class="text-sm text-gray-600">
						The rules every incoming message is screened against.
						<span v-if="!can.edit_patterns" class="text-gray-500">
							You can read the pack; editing it is restricted to System Manager.
						</span>
					</p>
					<Button v-if="can.edit_patterns" variant="solid" @click="editPattern(null)">
						<template #prefix><FeatherIcon name="plus" class="w-4 h-4" /></template>
						New rule
					</Button>
				</div>

				<div class="bg-white rounded-lg shadow-sm overflow-hidden">
					<div v-if="loading.patterns" class="p-6 text-sm text-gray-500">Loading pack…</div>
					<table v-else class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
							<tr>
								<th class="text-left px-4 py-2 font-medium w-20">Enabled</th>
								<th class="text-left px-4 py-2 font-medium">Rule</th>
								<th class="text-left px-4 py-2 font-medium">Type</th>
								<th class="text-left px-4 py-2 font-medium">Severity</th>
								<th class="text-left px-4 py-2 font-medium">Action</th>
								<th class="text-left px-4 py-2 font-medium"></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="p in patterns" :key="p.name" class="border-t">
								<td class="px-4 py-2">
									<input
										type="checkbox"
										:checked="p.enabled"
										:disabled="!can.edit_patterns || busyPattern === p.name"
										@change="toggle(p, $event.target.checked)"
									/>
								</td>
								<td class="px-4 py-2">
									<div class="text-gray-900">{{ p.pattern_name }}</div>
									<div class="text-xs text-gray-400 font-mono truncate max-w-md">{{ p.pattern }}</div>
								</td>
								<td class="px-4 py-2 text-gray-500">{{ p.pattern_type }}</td>
								<td class="px-4 py-2">
									<span class="text-xs px-2 py-0.5 rounded-full" :class="sevClass(p.severity)">{{ p.severity }}</span>
								</td>
								<td class="px-4 py-2 text-gray-500">{{ p.action }}</td>
								<td class="px-4 py-2 text-right">
									<Button v-if="can.edit_patterns" variant="ghost" @click="editPattern(p)">Edit</Button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>

			<!-- ── Tool policy ────────────────────────────────────────────── -->
			<section v-show="tab === 'policies'" class="space-y-4">
				<div class="bg-white rounded-lg shadow-sm p-4 flex items-start justify-between gap-4">
					<p class="text-sm text-gray-600">
						What an agent may <span class="font-medium">do</span>. Every tool call is checked
						against these before it runs — which tools the agent may use, which record types
						its arguments may name, and the numeric bounds those arguments must respect.
						<span v-if="!can.edit_policies" class="text-gray-500">
							You can read the rules; editing them is restricted to System Manager.
						</span>
					</p>
					<Button v-if="can.edit_policies" variant="solid" class="shrink-0" @click="editPolicy(null)">
						<template #prefix><FeatherIcon name="plus" class="w-4 h-4" /></template>
						New policy
					</Button>
				</div>

				<div class="bg-white rounded-lg shadow-sm overflow-hidden">
					<div v-if="loading.policies" class="p-6 text-sm text-gray-500">Loading policies…</div>
					<div v-else-if="!policies.length" class="p-6 text-sm text-gray-500">
						No policy rules yet. Until one exists, agents are limited only by what their
						diagrams grant them.
					</div>
					<table v-else class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
							<tr>
								<th class="text-left px-4 py-2 font-medium w-20">Enabled</th>
								<th class="text-left px-4 py-2 font-medium">Rule</th>
								<th class="text-left px-4 py-2 font-medium">Applies to</th>
								<th class="text-left px-4 py-2 font-medium">Bounds</th>
								<th class="text-left px-4 py-2 font-medium">Action</th>
								<th class="text-left px-4 py-2 font-medium"></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="p in policies" :key="p.name" class="border-t align-top">
								<td class="px-4 py-2">
									<input
										type="checkbox"
										:checked="p.enabled"
										:disabled="!can.edit_policies || busyPolicy === p.name"
										@change="togglePolicy(p, $event.target.checked)"
									/>
								</td>
								<td class="px-4 py-2">
									<div class="text-gray-900">{{ p.rule_name }}</div>
									<div v-if="p.category" class="text-xs text-gray-400">{{ p.category }}</div>
									<div v-if="p.exempt_agents && p.exempt_agents.length" class="text-xs text-amber-700 mt-0.5">
										Exempt: {{ p.exempt_agents.map((a) => a.agent_configuration).join(", ") }}
									</div>
								</td>
								<td class="px-4 py-2 text-gray-600">
									<!-- An empty tool scope means EVERY tool, which is the one thing a
									     reviewer must not have to infer from a blank cell. -->
									<div v-if="lines(p.restricted_tools).length" class="font-mono text-xs">
										{{ lines(p.restricted_tools).join(", ") }}
									</div>
									<div v-else class="text-xs text-amber-700">every tool</div>
									<div v-if="lines(p.restricted_doctypes).length" class="text-xs text-gray-500 mt-0.5">
										on {{ lines(p.restricted_doctypes).join(", ") }}
									</div>
									<div
										v-if="lines(p.restricted_doctypes).length && p.respect_user_permissions"
										class="text-xs text-amber-700 mt-0.5"
									>
										waived for users who already hold the permission
									</div>
								</td>
								<td class="px-4 py-2">
									<div
										v-for="l in lines(p.parameter_limits)"
										:key="l"
										class="font-mono text-xs text-gray-700"
									>{{ l }}</div>
									<span v-if="!lines(p.parameter_limits).length" class="text-xs text-gray-400">—</span>
								</td>
								<td class="px-4 py-2">
									<span class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700">Deny</span>
								</td>
								<td class="px-4 py-2 text-right whitespace-nowrap">
									<Button v-if="can.edit_policies" variant="ghost" @click="editPolicy(p)">Edit</Button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<!-- Proof the rules are live. Without it the tab shows intent and
				     never evidence, and a rule that silently matches nothing looks
				     exactly like one that is working. -->
				<!-- A rule that could not be APPLIED is not the same as a rule
				     firing, and showing them in one list made a broken ceiling
				     read as a working one. This one goes first because it is
				     the one that needs somebody. -->
				<div v-if="policyProblems.length" class="bg-white rounded-lg shadow-sm overflow-hidden border border-amber-200">
					<div class="px-4 py-3 border-b bg-amber-50">
						<h3 class="text-sm font-medium text-amber-900">Rules that could not be applied</h3>
						<p class="text-xs text-amber-800">
							Nothing was blocked by these. A limit line the interceptor cannot read is a
							ceiling that looks enforced and is not — open the rule and fix it.
						</p>
					</div>
					<div v-for="v in policyProblems" :key="v.name" class="border-t px-4 py-2">
						<div class="flex items-baseline gap-2">
							<span class="text-xs text-gray-400 whitespace-nowrap">{{ shortTime(v.creation) }}</span>
							<span class="text-sm text-gray-900">{{ v.method }}</span>
						</div>
						<pre class="text-xs text-gray-500 whitespace-pre-wrap mt-1 max-h-20 overflow-auto">{{ v.error }}</pre>
					</div>
				</div>

				<div class="bg-white rounded-lg shadow-sm overflow-hidden">
					<div class="px-4 py-3 border-b flex items-center justify-between">
						<div>
							<h3 class="text-sm font-medium text-gray-900">Recent blocks</h3>
							<p class="text-xs text-gray-500">
								The last calls these rules stopped. Read from the Error Log the interceptor
								writes to — a tail, not a report.
							</p>
						</div>
						<Button variant="ghost" @click="loadViolations">Refresh</Button>
					</div>
					<div v-if="!policyBlocks.length" class="p-4 text-sm text-gray-500">
						Nothing has been blocked yet.
					</div>
					<div v-for="v in policyBlocks" :key="v.name" class="border-t px-4 py-2">
						<div class="flex items-baseline gap-2">
							<span class="text-xs text-gray-400 whitespace-nowrap">{{ shortTime(v.creation) }}</span>
							<span class="text-sm text-gray-900">{{ v.method }}</span>
						</div>
						<pre class="text-xs text-gray-500 whitespace-pre-wrap mt-1 max-h-24 overflow-auto">{{ v.error }}</pre>
					</div>
				</div>
			</section>

			<!-- ── Locked conversations ───────────────────────────────────── -->
			<section v-show="tab === 'locks'" class="space-y-4">
				<div class="bg-white rounded-lg shadow-sm overflow-hidden">
					<div v-if="loading.locks" class="p-6 text-sm text-gray-500">Loading locks…</div>
					<div v-else-if="!locks.length" class="p-6 text-sm text-gray-500">
						No conversations are frozen.
					</div>
					<table v-else class="w-full text-sm">
						<thead class="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
							<tr>
								<th class="text-left px-4 py-2 font-medium">Status</th>
								<th class="text-left px-4 py-2 font-medium">User</th>
								<th class="text-left px-4 py-2 font-medium">Agent</th>
								<th class="text-left px-4 py-2 font-medium">Blocks</th>
								<th class="text-left px-4 py-2 font-medium">Locked</th>
								<th class="text-left px-4 py-2 font-medium">Release</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="l in locks" :key="l.name" class="border-t align-top">
								<td class="px-4 py-2">
									<span class="text-xs px-2 py-0.5 rounded-full" :class="l.status === 'Locked' ? 'bg-red-50 text-red-700' : 'bg-gray-100 text-gray-600'">
										{{ l.status }}
									</span>
								</td>
								<td class="px-4 py-2">{{ l.user }}</td>
								<td class="px-4 py-2">{{ l.agent_configuration || "—" }}</td>
								<td class="px-4 py-2 text-gray-500">{{ l.blocked_count }}</td>
								<td class="px-4 py-2 text-gray-500 whitespace-nowrap">{{ shortTime(l.locked_at) }}</td>
								<td class="px-4 py-2">
									<div v-if="l.status !== 'Locked'" class="text-xs text-gray-500">
										by {{ l.released_by }} · {{ shortTime(l.released_at) }}
										<div v-if="l.release_notes" class="text-gray-400 italic">“{{ l.release_notes }}”</div>
									</div>
									<div v-else-if="l.user === me" class="text-xs text-gray-500">
										You cannot release your own — another reviewer has to.
									</div>
									<Button v-else variant="subtle" @click="openRelease(l)">Release…</Button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>
		</main>

		<!-- ── Event detail ───────────────────────────────────────────────── -->
		<div v-if="openedEvent" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-6" @click.self="openedEvent = null">
			<div class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[85vh] overflow-auto">
				<div class="flex items-center justify-between border-b px-5 py-3">
					<h2 class="font-semibold text-gray-900">Security event</h2>
					<button class="text-gray-400 hover:text-gray-700" @click="openedEvent = null">✕</button>
				</div>
				<div class="p-5 space-y-4">
					<dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
						<div v-for="f in detailFields" :key="f" class="contents">
							<dt class="text-gray-500">{{ labelOf(f) }}</dt>
							<dd class="text-gray-900 break-all">{{ openedEvent[f] ?? "—" }}</dd>
						</div>
					</dl>

					<!-- The point of the hash: it proves what was seen without keeping it. -->
					<div class="rounded-lg bg-gray-50 border p-3 text-sm">
						<div class="font-medium text-gray-700">Screened content</div>
						<p class="text-gray-600 mt-1">
							Not shown, because it is not stored. The text was hashed and measured at the
							boundary and then dropped — the hash below identifies it without keeping it.
						</p>
						<div class="mt-2 font-mono text-xs text-gray-700 break-all">
							{{ openedEvent.content_hash || "no hash recorded" }}
							<span class="text-gray-400">· {{ openedEvent.content_length || 0 }} chars</span>
						</div>
					</div>

					<div class="flex items-center gap-3 border-t pt-4">
						<!-- Shown only when the server could not choose: an agent with one
						     suite stays a single click. -->
						<select v-if="suiteChoices.length" v-model="chosenSuite" class="border rounded px-2 py-1 text-sm">
							<option value="">Choose a suite…</option>
							<option v-for="s in suiteChoices" :key="s.name" :value="s.name">
								{{ s.title }} ({{ s.suite_type }})
							</option>
						</select>
						<button
							class="btn-primary"
							:disabled="promoting || !!openedEvent.promoted_case || (suiteChoices.length && !chosenSuite)"
							@click="promote"
						>
							{{ promoting ? "Promoting…" : openedEvent.promoted_case ? "Already an eval case" : "Promote to eval case" }}
						</button>
						<router-link
							v-if="openedEvent.promoted_case"
							:to="`/processa/evals`"
							class="text-sm text-blue-600 hover:underline"
						>
							{{ openedEvent.promoted_case }} →
						</router-link>
						<span v-if="promoteNote" class="text-sm" :class="promoteError ? 'text-red-600' : 'text-green-700'">
							{{ promoteNote }}
						</span>
					</div>
				</div>
			</div>
		</div>

		<!-- ── Pattern editor ─────────────────────────────────────────────── -->
		<Dialog
			:modelValue="!!patternDraft"
			:options="{ title: patternDraft && patternDraft.name ? 'Edit rule' : 'New rule', size: 'xl' }"
			@update:modelValue="(v) => { if (!v) patternDraft = null }"
		>
			<template #body-content>
				<div v-if="patternDraft" class="space-y-4">
					<FormControl type="text" label="Rule name" v-model="patternDraft.pattern_name" />
					<FormControl
						type="textarea"
						label="Pattern"
						:rows="3"
						v-model="patternDraft.pattern"
						class="font-mono"
					/>
					<div class="grid grid-cols-2 gap-4">
						<FormControl type="select" label="Type" v-model="patternDraft.pattern_type" :options="enumOptions.pattern_type" />
						<FormControl type="select" label="Match mode" v-model="patternDraft.match_mode" :options="enumOptions.match_mode" />
						<FormControl type="select" label="Severity" v-model="patternDraft.severity" :options="enumOptions.severity" />
						<FormControl type="select" label="Action" v-model="patternDraft.action" :options="enumOptions.action" />
						<div class="col-span-2">
							<FormControl type="select" label="Boundary scope" v-model="patternDraft.boundary_scope" :options="enumOptions.boundary_scope" />
						</div>
					</div>
					<FormControl type="textarea" label="Notes" :rows="2" v-model="patternDraft.notes" />
					<FormControl type="checkbox" label="Enabled" v-model="patternEnabled" />
					<ErrorMessage :message="patternError" />
				</div>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button variant="subtle" @click="patternDraft = null">Cancel</Button>
					<Button variant="solid" :loading="savingPattern" @click="savePattern">Save rule</Button>
				</div>
			</template>
		</Dialog>

		<!-- ── Policy editor ──────────────────────────────────────────────── -->
		<Dialog
			:modelValue="!!policyDraft"
			:options="{ title: policyDraft && policyDraft.name ? 'Edit policy' : 'New policy', size: '3xl' }"
			@update:modelValue="(v) => { if (!v) policyDraft = null }"
		>
			<template #body-content>
				<div v-if="policyDraft" class="space-y-5">
					<div class="grid grid-cols-2 gap-4">
						<FormControl type="text" label="Rule name" v-model="policyDraft.rule_name" />
						<FormControl type="select" label="Category" v-model="policyDraft.category" :options="policyEnumOptions.category" />
					</div>

					<!-- What it matches. Either criterion is enough — a rule may bound
					     WHAT a tool acts on, HOW MUCH it acts with, or both. -->
					<div class="border rounded-lg p-4 space-y-4">
						<div>
							<h4 class="text-sm font-medium text-gray-900">What this rule matches</h4>
							<p class="text-xs text-gray-500">
								Set at least one. A rule that matches nothing cannot be saved.
							</p>
						</div>
						<FormControl
							type="textarea"
							label="Only these tools"
							:rows="2"
							v-model="policyDraft.restricted_tools"
							class="font-mono"
							placeholder="add_numbers"
						/>
						<p class="-mt-2 text-xs" :class="policyDraft.restricted_tools ? 'text-gray-500' : 'text-amber-700'">
							One tool name per line.
							{{ policyDraft.restricted_tools
								? "Only these tools are checked."
								: "Empty means EVERY tool every agent calls — usually not what you want alongside a numeric bound." }}
						</p>
						<div class="grid grid-cols-2 gap-4">
							<div>
								<FormControl
									type="textarea"
									label="Restricted DocTypes"
									:rows="3"
									v-model="policyDraft.restricted_doctypes"
									placeholder="Salary Slip"
								/>
								<FormControl
									type="checkbox"
									class="mt-2"
									label="Respect user permissions"
									v-model="policyDraft.respect_user_permissions"
								/>
								<p class="mt-1 text-xs" :class="policyDraft.respect_user_permissions ? 'text-amber-700' : 'text-gray-500'">
									{{ policyDraft.respect_user_permissions
										? "This rule stands down for anyone who already holds the matching Frappe permission — read for a read-only tool, write for anything else. Leave off for rules that must hold whoever is asking."
										: "This rule applies to everyone, whatever permissions they hold." }}
								</p>
							</div>
							<FormControl
								type="textarea"
								label="Parameter limits"
								:rows="3"
								v-model="policyDraft.parameter_limits"
								class="font-mono"
								placeholder="amount <= 5000"
							/>
						</div>
						<p class="-mt-2 text-xs text-gray-500">
							One per line. DocTypes are matched whole, at any depth in the arguments.
							Limits are written <code>parameter &lt;= number</code> using
							{{ (policyOptions.limit_operators || []).join(", ") }} — nothing else is
							evaluated, so a rule can never run code.
						</p>
					</div>

					<!-- What happens. Refusing is the only action, so this is a
					     statement rather than a choice — a one-option dropdown
					     implies alternatives that do not exist. -->
					<div class="border rounded-lg p-4 space-y-4">
						<div>
							<h4 class="text-sm font-medium text-gray-900">What happens when it matches</h4>
							<p class="text-xs text-gray-500">
								The call is aborted before the tool runs and the agent is told why, so it
								can take a different approach or tell the user.
							</p>
						</div>
						<FormControl
							type="textarea"
							label="Violation message"
							:rows="2"
							v-model="policyDraft.violation_message"
							placeholder="Payments above KD 5,000 need a person."
						/>
						<p class="-mt-2 text-xs text-gray-500">
							What the agent is told, and what it repeats to the user. Leave empty for a
							generated one.
						</p>
					</div>

					<!-- Exemptions. -->
					<div class="border rounded-lg p-4 space-y-3">
						<div class="flex items-center justify-between">
							<div>
								<h4 class="text-sm font-medium text-gray-900">Exempt agents</h4>
								<p class="text-xs text-gray-500">Agents this rule does not apply to.</p>
							</div>
							<Button variant="subtle" @click="addExempt">
								<template #prefix><FeatherIcon name="plus" class="w-4 h-4" /></template>
								Add
							</Button>
						</div>
						<div
							v-for="(row, i) in policyDraft.exempt_agents"
							:key="i"
							class="flex gap-2 items-start"
						>
							<FormControl
								type="autocomplete"
								class="flex-1"
								:options="agentOptionsForPolicy"
								:modelValue="row.agent_configuration"
								@update:modelValue="(v) => (row.agent_configuration = v?.value ?? v ?? '')"
							/>
							<FormControl
								type="text"
								class="flex-1"
								v-model="row.reason"
								placeholder="Why is it exempt?"
							/>
							<Button variant="ghost" @click="policyDraft.exempt_agents.splice(i, 1)">
								<FeatherIcon name="x" class="w-4 h-4" />
							</Button>
						</div>
					</div>

					<FormControl type="checkbox" label="Enabled" v-model="policyEnabled" />
					<ErrorMessage :message="policyError" />
				</div>
			</template>
			<template #actions>
				<div class="flex justify-between gap-2">
					<Button
						v-if="policyDraft && policyDraft.name"
						variant="subtle"
						theme="red"
						:loading="deletingPolicy"
						@click="deletePolicy"
					>Delete</Button>
					<span v-else></span>
					<span class="flex gap-2">
						<Button variant="subtle" @click="policyDraft = null">Cancel</Button>
						<Button variant="solid" :loading="savingPolicy" @click="savePolicy">Save policy</Button>
					</span>
				</div>
			</template>
		</Dialog>

		<!-- ── Release dialog ─────────────────────────────────────────────── -->
		<Dialog
			:modelValue="!!releasing"
			:options="{ title: 'Release this conversation', size: 'lg' }"
			@update:modelValue="(v) => { if (!v) releasing = null }"
		>
			<template #body-content>
				<div v-if="releasing" class="space-y-4">
					<p class="text-sm text-gray-600">
						Releasing lets <span class="font-medium">{{ releasing.user }}</span> talk to
						<span class="font-medium">{{ releasing.agent_configuration }}</span> again.
						Your note is kept as the audit trail.
					</p>
					<FormControl
						type="textarea"
						label="Reason"
						:rows="3"
						v-model="releaseNotes"
						placeholder="Why is this being released?"
					/>
					<ErrorMessage :message="releaseError" />
				</div>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button variant="subtle" @click="releasing = null">Cancel</Button>
					<Button
						variant="solid"
						theme="red"
						:loading="releaseBusy"
						:disabled="!releaseNotes.trim()"
						@click="doRelease"
					>Release</Button>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// WI-001970: the security operation, in the SPA.
//
// Read-mostly by design. Every write here is a call into the module that owns
// the behaviour — the pattern doctype, 15.2's promote method, 15.3's release
// action — so this screen can never become a second, divergent implementation
// of the rules it displays.
import { computed, onMounted, reactive, ref } from "vue"
import { Button, Dialog, ErrorMessage, FeatherIcon, FormControl, frappeRequest } from "frappe-ui"

const API = "/api/method/one_bpmn.api.security_api."

const tab = ref("events")
const can = ref({ edit_patterns: false, edit_policies: false, release_locks: false, read_events: true })
const loading = reactive({ events: false, patterns: false, locks: false, policies: false })

const events = ref([])
const total = ref(0)
const start = ref(0)
// Reactive so the toolbar can change it. 200 is the server's own cap on
// page_length, so the options stop short of it rather than asking for a page
// the endpoint will silently shrink.
const pageLength = ref(50)
const PAGE_SIZES = [
	{ label: "20", value: 20 },
	{ label: "50", value: 50 },
	{ label: "100", value: 100 },
	{ label: "200", value: 200 },
]
// The select hands back a string, and the pager does arithmetic on this
// ("start + pageLength"), which would silently concatenate. Everything numeric
// reads pageSize rather than the raw model.
const pageSize = computed(() => Number(pageLength.value) || 50)
const options = ref({ agents: [], boundaries: [], actions: [], severities: [] })
const filters = reactive({ agent: "", boundary: "", action: "", search: "" })

// The empty option carries the filter's name, so the control reads as a label
// until it is set — the pattern the Instances toolbar uses. Values still come
// from event_filter_options, which returns what is actually in the log rather
// than every value the schema allows.
function selectOptions(all, allLabel) {
	return [{ label: allLabel, value: "" }, ...all.map((v) => ({ label: v, value: v }))]
}
const agentOptions = computed(() => selectOptions(options.value.agents, "All agents"))
const boundaryOptions = computed(() => selectOptions(options.value.boundaries, "All boundaries"))
const actionOptions = computed(() => selectOptions(options.value.actions, "All actions"))

const patterns = ref([])
const locks = ref([])
const me = ref("")

const openedEvent = ref(null)
const promoting = ref(false)
const promoteNote = ref("")
const promoteError = ref(false)
const suiteChoices = ref([])
const chosenSuite = ref("")

const patternDraft = ref(null)
const savingPattern = ref(false)
const patternError = ref("")
const busyPattern = ref("")

// WI-001645: what an agent may DO, alongside what may be said to it.
const policies = ref([])
const policyDraft = ref(null)
const savingPolicy = ref(false)
const deletingPolicy = ref(false)
const policyError = ref("")
const busyPolicy = ref("")
const policyOptions = ref({ category: [], agents: [], limit_operators: [] })
const policyBlocks = ref([])
const policyProblems = ref([])

const releasing = ref(null)
const releaseNotes = ref("")
const releaseBusy = ref(false)
const releaseError = ref("")

// Fetched from the doctype rather than written out here. A hand-copied option
// list rots the moment a story adds a pattern type, and it rots silently — the
// editor offers a value the doctype rejects, or hides one it accepts.
const enums = ref({
	pattern_type: [], match_mode: [], severity: [],
	action: [], boundary_scope: [], source_taxonomy: [],
})

// FormControl wants {label, value}; pattern_options serves bare strings.
const enumOptions = computed(() => {
	const out = {}
	for (const [key, values] of Object.entries(enums.value)) {
		out[key] = (values || []).map((v) => ({ label: v, value: v }))
	}
	return out
})

// The doctype stores enabled as 1/0; a checkbox is a boolean.
const patternEnabled = computed({
	get: () => Boolean(patternDraft.value && patternDraft.value.enabled),
	set: (v) => { if (patternDraft.value) patternDraft.value.enabled = v ? 1 : 0 },
})

// AC2 is "everything recorded", so the panel shows whatever get_event returned
// rather than keeping its own list of fields to show. A second hard-coded list
// only has to agree with the server's, and it already did not — `creation` was
// being returned and silently never displayed. The server still names the
// fields it will hand out, deliberately, so a field added to the doctype cannot
// start leaking through here; this just stops the screen hiding what it was
// given.
//
// DETAIL_ORDER is presentation only: these first, in this order, then anything
// else the server sent. A new field appears at the end rather than not at all.
const DETAIL_ORDER = [
	"name", "detected_at", "agent_configuration", "conversation", "boundary", "stage",
	"action", "severity", "rule", "rule_type", "classifier", "matched_pattern",
	"correlation_id", "run", "bpmn_id", "owner", "detail",
]

// Rendered elsewhere in the dialog, so listing them again would duplicate them:
// the hash and length have their own block, and the rest are UI state rather
// than things the boundary recorded.
const DETAIL_RENDERED_SEPARATELY = ["content_hash", "content_length", "content_stored", "promoted_case"]

const detailFields = computed(() => {
	const ev = openedEvent.value
	if (!ev) return []
	const present = Object.keys(ev).filter((k) => !DETAIL_RENDERED_SEPARATELY.includes(k))
	return [
		...DETAIL_ORDER.filter((f) => present.includes(f)),
		...present.filter((f) => !DETAIL_ORDER.includes(f)),
	]
})

const policyEnumOptions = computed(() => ({
	category: (policyOptions.value.category || []).map((v) => ({ label: v, value: v })),
}))
const agentOptionsForPolicy = computed(() =>
	(policyOptions.value.agents || []).map((v) => ({ label: v, value: v }))
)
// The doctype stores enabled as 1/0; a checkbox is a boolean.
const policyEnabled = computed({
	get: () => Boolean(policyDraft.value && policyDraft.value.enabled),
	set: (v) => { if (policyDraft.value) policyDraft.value.enabled = v ? 1 : 0 },
})

const tabs = computed(() => [
	{ key: "events", label: "Events", count: total.value || null },
	{ key: "patterns", label: "Pattern pack", count: patterns.value.length || null },
	{ key: "policies", label: "Tool policy", count: policies.value.filter((p) => p.enabled).length || null },
	{ key: "locks", label: "Locked conversations", count: locks.value.filter((l) => l.status === "Locked").length || null },
])

const anyFilter = computed(() => Boolean(filters.agent || filters.boundary || filters.action || filters.search))

function labelOf(f) {
	return f.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}
function shortTime(v) {
	if (!v) return "—"
	return String(v).replace("T", " ").slice(0, 16)
}
function actionClass(a) {
	if (a === "Block") return "bg-red-50 text-red-700"
	if (a === "Flag") return "bg-amber-50 text-amber-700"
	return "bg-gray-100 text-gray-600"
}
// The doctype stores these as newline-separated text; every cell that shows one
// needs the same split, so it lives here rather than in five templates.
function lines(v) {
	return String(v || "")
		.split("\n")
		.map((x) => x.trim())
		.filter(Boolean)
}
function sevClass(s) {
	if (s === "Critical") return "bg-red-50 text-red-700"
	if (s === "High") return "bg-orange-50 text-orange-700"
	if (s === "Medium") return "bg-amber-50 text-amber-700"
	return "bg-gray-100 text-gray-600"
}

async function call(method, params) {
	return frappeRequest({ url: API + method, method: "POST", params: params || {} })
}

async function loadEvents(from = 0) {
	loading.events = true
	try {
		const r = await call("list_events", {
			agent: filters.agent || undefined,
			boundary: filters.boundary || undefined,
			action: filters.action || undefined,
			search: filters.search || undefined,
			start: Math.max(0, from),
			page_length: pageSize.value,
		})
		events.value = r.events || []
		total.value = r.total || 0
		start.value = r.start || 0
	} finally {
		loading.events = false
	}
}

function changePageSize() {
	// Back to the first page: the old offset means something different under a
	// new page size, and on a big jump it can land past the end of the results.
	loadEvents(0)
}

function resetFilters() {
	filters.agent = filters.boundary = filters.action = filters.search = ""
	loadEvents(0)
}

async function openEvent(name) {
	promoteNote.value = ""
	promoteError.value = false
	suiteChoices.value = []
	chosenSuite.value = ""
	openedEvent.value = await call("get_event", { name })
}

async function promote() {
	promoting.value = true
	promoteNote.value = ""
	promoteError.value = false
	try {
		const r = await call("promote_event", {
			event: openedEvent.value.name,
			suite: chosenSuite.value || undefined,
		})
		openedEvent.value.promoted_case = r.case
		suiteChoices.value = []
		// Saying WHICH of the two happened matters: clicking twice otherwise looks
		// like the first click failed.
		// A new adversarial suite may have been made for this agent on the way
		// through. That is a new go-live gate, so it is said out loud rather than
		// left for the reviewer to discover in the Evals screen.
		const where = r.suite_created
			? ` in a new adversarial suite, ${r.suite_title || r.suite}.`
			: r.suite_title
				? ` in ${r.suite_title}.`
				: "."
		promoteNote.value = r.already_promoted
			? "Already promoted — showing the existing case."
			: `Created eval case ${r.case}${where}`
	} catch (e) {
		promoteError.value = true
		promoteNote.value = e?.messages?.join("\n") || e?.message || String(e)
		// "Pick a suite" is not really an error, it is a question. Offer the
		// candidates rather than leaving the reviewer with a dead end.
		if (/suite/i.test(promoteNote.value) && !suiteChoices.value.length) {
			suiteChoices.value = (await call("suites_for_event", { event: openedEvent.value.name }).catch(() => [])) || []
			if (suiteChoices.value.length) {
				promoteNote.value = "This agent has more than one adversarial suite — choose which one to add the case to."
				promoteError.value = false
			}
		}
	} finally {
		promoting.value = false
	}
}

async function loadPatterns() {
	loading.patterns = true
	try {
		const r = await call("list_patterns")
		patterns.value = r.patterns || []
		can.value.edit_patterns = r.can_edit
	} finally {
		loading.patterns = false
	}
}

async function toggle(p, enabled) {
	busyPattern.value = p.name
	try {
		const r = await call("set_pattern_enabled", { name: p.name, enabled: enabled ? 1 : 0 })
		p.enabled = r.enabled
	} catch (e) {
		p.enabled = p.enabled ? 0 : 1 // put the checkbox back
	} finally {
		busyPattern.value = ""
	}
}

function editPattern(p) {
	patternError.value = ""
	// Defaults come from the options the doctype actually serves. They used to be
	// written out here, and two of the five were values it rejects — pattern_type
	// "Regex" (that is a match_mode) and match_mode "Case Insensitive" (not an
	// option at all). A new rule saved without touching those two dropdowns
	// failed validation, so "＋ New rule" → "Save rule" could not succeed.
	const first = (key, fallback) => (enums.value[key] || [])[0] || fallback
	patternDraft.value = p
		? { ...p }
		: {
				pattern_name: "",
				pattern: "",
				pattern_type: first("pattern_type", "Other"),
				match_mode: first("match_mode", "regex"),
				severity: "Medium",
				action: first("action", "Log"),
				boundary_scope: "input",
				notes: "",
				enabled: 1,
			}
}

async function savePattern() {
	savingPattern.value = true
	patternError.value = ""
	try {
		await call("save_pattern", { pattern: JSON.stringify(patternDraft.value), name: patternDraft.value.name || undefined })
		patternDraft.value = null
		await loadPatterns()
	} catch (e) {
		// A bad regex is rejected by the doctype's own validation; show it here
		// rather than letting the dialog close on a rule that was never saved.
		patternError.value = e?.messages?.join("\n") || e?.message || String(e)
	} finally {
		savingPattern.value = false
	}
}

async function loadPolicies() {
	loading.policies = true
	try {
		const r = await call("list_policies")
		policies.value = r.policies || []
		can.value.edit_policies = r.can_edit
	} finally {
		loading.policies = false
	}
}

async function loadViolations() {
	const r = (await call("policy_violations", { limit: 20 }).catch(() => null)) || {}
	policyBlocks.value = r.blocks || []
	policyProblems.value = r.problems || []
}

async function togglePolicy(p, enabled) {
	busyPolicy.value = p.name
	try {
		const r = await call("set_policy_enabled", { name: p.name, enabled: enabled ? 1 : 0 })
		p.enabled = r.enabled
	} catch (e) {
		p.enabled = p.enabled ? 0 : 1 // put the checkbox back
	} finally {
		busyPolicy.value = ""
	}
}

function editPolicy(p) {
	policyError.value = ""
	policyDraft.value = p
		? { ...p, exempt_agents: (p.exempt_agents || []).map((r) => ({ ...r })) }
		: {
				rule_name: "",
				// "Other", not the first option: a category is a label for the
				// reviewer, and defaulting to "Identity & Permissions" quietly
				// mislabels every rule somebody does not think to change.
				category: "Other",
				// The only action there is; sent explicitly so the field is never
				// left to the doctype default by accident.
				action: "Deny",
				restricted_tools: "",
				restricted_doctypes: "",
				// Off by default. Deferring to the asker's permissions is a
				// relaxation, so it is something a person turns on deliberately.
				respect_user_permissions: 0,
				parameter_limits: "",
				violation_message: "",
				exempt_agents: [],
				enabled: 1,
			}
}

function addExempt() {
	if (policyDraft.value) policyDraft.value.exempt_agents.push({ agent_configuration: "", reason: "" })
}

async function savePolicy() {
	savingPolicy.value = true
	policyError.value = ""
	try {
		await call("save_policy", {
			policy: JSON.stringify(policyDraft.value),
			name: policyDraft.value.name || undefined,
		})
		policyDraft.value = null
		await loadPolicies()
	} catch (e) {
		// The doctype refuses a rule that matches nothing and an unreadable
		// limit line. Those messages are the useful part — show them here rather
		// than closing on a rule that never saved.
		policyError.value = e?.messages?.join("\n") || e?.message || String(e)
	} finally {
		savingPolicy.value = false
	}
}

async function deletePolicy() {
	if (!window.confirm(`Delete the policy "${policyDraft.value.rule_name}"? Agents stop being checked against it immediately.`)) return
	deletingPolicy.value = true
	policyError.value = ""
	try {
		await call("delete_policy", { name: policyDraft.value.name })
		policyDraft.value = null
		await loadPolicies()
	} catch (e) {
		policyError.value = e?.messages?.join("\n") || e?.message || String(e)
	} finally {
		deletingPolicy.value = false
	}
}

async function loadLocks() {
	loading.locks = true
	try {
		const r = await call("list_locks")
		locks.value = r.locks || []
		me.value = r.me
	} finally {
		loading.locks = false
	}
}

function openRelease(l) {
	releasing.value = l
	releaseNotes.value = ""
	releaseError.value = ""
}

async function doRelease() {
	releaseBusy.value = true
	releaseError.value = ""
	try {
		await call("release", { lock: releasing.value.name, notes: releaseNotes.value })
		releasing.value = null
		await loadLocks()
	} catch (e) {
		releaseError.value = e?.messages?.join("\n") || e?.message || String(e)
	} finally {
		releaseBusy.value = false
	}
}

onMounted(async () => {
	try {
		can.value = await call("can_manage")
	} catch (e) {
		/* leave the conservative defaults */
	}
	options.value = await call("event_filter_options").catch(() => options.value)
	enums.value = await call("pattern_options").catch(() => enums.value)
	policyOptions.value = await call("policy_options").catch(() => policyOptions.value)
	await Promise.all([loadEvents(0), loadPatterns(), loadPolicies(), loadLocks(), loadViolations()])
})
</script>

<style scoped>
.btn-primary {
	padding: 0.375rem 0.75rem;
	font-size: 0.875rem;
	border-radius: 0.375rem;
	background: #171717;
	color: #fff;
}
.btn-primary:disabled {
	opacity: 0.5;
}
.btn-plain {
	padding: 0.375rem 0.75rem;
	font-size: 0.875rem;
	border-radius: 0.375rem;
	border: 1px solid var(--border-color, #d1d8dd);
	background: #fff;
}
</style>
