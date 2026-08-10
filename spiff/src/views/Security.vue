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
			<Button v-if="anyFilter" variant="ghost" class="ml-auto" @click="resetFilters">
				Clear filters
			</Button>
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
							<button class="px-2 py-1 border rounded disabled:opacity-40" :disabled="start === 0" @click="loadEvents(start - pageLength)">
								Previous
							</button>
							<button class="px-2 py-1 border rounded disabled:opacity-40" :disabled="start + pageLength >= total" @click="loadEvents(start + pageLength)">
								Next
							</button>
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
					<button v-if="can.edit_patterns" class="btn-primary" @click="editPattern(null)">＋ New rule</button>
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
									<button v-if="can.edit_patterns" class="text-xs text-blue-600 hover:underline" @click="editPattern(p)">Edit</button>
								</td>
							</tr>
						</tbody>
					</table>
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
									<button v-else class="text-xs text-blue-600 hover:underline" @click="openRelease(l)">Release…</button>
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
		<div v-if="patternDraft" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-6" @click.self="patternDraft = null">
			<div class="bg-white rounded-lg shadow-xl max-w-xl w-full max-h-[85vh] overflow-auto">
				<div class="flex items-center justify-between border-b px-5 py-3">
					<h2 class="font-semibold text-gray-900">{{ patternDraft.name ? "Edit rule" : "New rule" }}</h2>
					<button class="text-gray-400 hover:text-gray-700" @click="patternDraft = null">✕</button>
				</div>
				<div class="p-5 space-y-3">
					<label class="block">
						<span class="text-xs text-gray-500">Rule name</span>
						<input v-model="patternDraft.pattern_name" type="text" class="border rounded px-2 py-1 text-sm w-full" />
					</label>
					<label class="block">
						<span class="text-xs text-gray-500">Pattern</span>
						<textarea v-model="patternDraft.pattern" rows="3" class="border rounded px-2 py-1 text-sm w-full font-mono"></textarea>
					</label>
					<div class="grid grid-cols-2 gap-3">
						<label class="block">
							<span class="text-xs text-gray-500">Type</span>
							<select v-model="patternDraft.pattern_type" class="border rounded px-2 py-1 text-sm w-full">
								<option v-for="o in enums.pattern_type" :key="o" :value="o">{{ o }}</option>
							</select>
						</label>
						<label class="block">
							<span class="text-xs text-gray-500">Match mode</span>
							<select v-model="patternDraft.match_mode" class="border rounded px-2 py-1 text-sm w-full">
								<option v-for="o in enums.match_mode" :key="o" :value="o">{{ o }}</option>
							</select>
						</label>
						<label class="block">
							<span class="text-xs text-gray-500">Severity</span>
							<select v-model="patternDraft.severity" class="border rounded px-2 py-1 text-sm w-full">
								<option v-for="o in enums.severity" :key="o" :value="o">{{ o }}</option>
							</select>
						</label>
						<label class="block">
							<span class="text-xs text-gray-500">Action</span>
							<select v-model="patternDraft.action" class="border rounded px-2 py-1 text-sm w-full">
								<option v-for="o in enums.action" :key="o" :value="o">{{ o }}</option>
							</select>
						</label>
						<label class="block col-span-2">
							<span class="text-xs text-gray-500">Boundary scope</span>
							<select v-model="patternDraft.boundary_scope" class="border rounded px-2 py-1 text-sm w-full">
								<option v-for="o in enums.boundary_scope" :key="o" :value="o">{{ o }}</option>
							</select>
						</label>
					</div>
					<label class="block">
						<span class="text-xs text-gray-500">Notes</span>
						<textarea v-model="patternDraft.notes" rows="2" class="border rounded px-2 py-1 text-sm w-full"></textarea>
					</label>
					<label class="flex items-center gap-2 text-sm">
						<input type="checkbox" v-model="patternDraft.enabled" :true-value="1" :false-value="0" />
						Enabled
					</label>
					<p v-if="patternError" class="text-sm text-red-600 whitespace-pre-line">{{ patternError }}</p>
				</div>
				<div class="flex justify-end gap-2 border-t px-5 py-3">
					<button class="btn-plain" @click="patternDraft = null">Cancel</button>
					<button class="btn-primary" :disabled="savingPattern" @click="savePattern">
						{{ savingPattern ? "Saving…" : "Save rule" }}
					</button>
				</div>
			</div>
		</div>

		<!-- ── Release dialog ─────────────────────────────────────────────── -->
		<div v-if="releasing" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-6" @click.self="releasing = null">
			<div class="bg-white rounded-lg shadow-xl max-w-lg w-full">
				<div class="border-b px-5 py-3 font-semibold text-gray-900">Release this conversation</div>
				<div class="p-5 space-y-3 text-sm">
					<p class="text-gray-600">
						Releasing lets <span class="font-medium">{{ releasing.user }}</span> talk to
						<span class="font-medium">{{ releasing.agent_configuration }}</span> again.
						Your note is kept as the audit trail.
					</p>
					<textarea
						v-model="releaseNotes"
						rows="3"
						class="border rounded px-2 py-1 text-sm w-full"
						placeholder="Why is this being released?"
					></textarea>
					<p v-if="releaseError" class="text-red-600 whitespace-pre-line">{{ releaseError }}</p>
				</div>
				<div class="flex justify-end gap-2 border-t px-5 py-3">
					<button class="btn-plain" @click="releasing = null">Cancel</button>
					<button class="btn-primary" :disabled="releaseBusy || !releaseNotes.trim()" @click="doRelease">
						{{ releaseBusy ? "Releasing…" : "Release" }}
					</button>
				</div>
			</div>
		</div>
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
import { Button, FormControl, frappeRequest } from "frappe-ui"

const API = "/api/method/one_bpmn.api.security_api."

const tab = ref("events")
const can = ref({ edit_patterns: false, release_locks: false, read_events: true })
const loading = reactive({ events: false, patterns: false, locks: false })

const events = ref([])
const total = ref(0)
const start = ref(0)
const pageLength = 50
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

const tabs = computed(() => [
	{ key: "events", label: "Events", count: total.value || null },
	{ key: "patterns", label: "Pattern pack", count: patterns.value.length || null },
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
			page_length: pageLength,
		})
		events.value = r.events || []
		total.value = r.total || 0
		start.value = r.start || 0
	} finally {
		loading.events = false
	}
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
		promoteNote.value = r.already_promoted
			? "Already promoted — showing the existing case."
			: `Created eval case ${r.case}.`
	} catch (e) {
		promoteError.value = true
		promoteNote.value = e?.messages?.join("\n") || e?.message || String(e)
		// "Pick a suite" is not really an error, it is a question. Offer the
		// candidates rather than leaving the reviewer with a dead end.
		if (/suite/i.test(promoteNote.value) && !suiteChoices.value.length) {
			suiteChoices.value = (await call("suites_for_event", { event: openedEvent.value.name }).catch(() => [])) || []
			if (suiteChoices.value.length) {
				promoteNote.value = "This agent has more than one suite — choose which one to add the case to."
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
	patternDraft.value = p
		? { ...p }
		: {
				pattern_name: "", pattern: "", pattern_type: "Regex", match_mode: "Case Insensitive",
				severity: "Medium", action: "Log", boundary_scope: "input", notes: "", enabled: 1,
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
	await Promise.all([loadEvents(0), loadPatterns(), loadLocks()])
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
