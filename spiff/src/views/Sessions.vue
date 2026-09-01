<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Sessions</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						What each conversation is doing, what its agent remembers of it, and how long it is kept.
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

		<!-- ── Conversations ───────────────────────────────────────────── -->
		<div v-show="tab === 'conversations'" class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center">
			<FormControl type="select" v-model="filters.agent" :options="agentOptions" class="w-56" @change="load()" />
			<FormControl type="select" v-model="filters.status" :options="statusOptions" class="w-44" @change="load()" />
			<FormControl type="text" v-model="filters.search" placeholder="Search titles" class="w-64" @change="load()" />
			<Button :loading="loading" @click="load()">Refresh</Button>

			<!-- Page size, right-aligned like the Instances and Security toolbars.
			     A busy site accumulates conversations without bound, so how many to
			     pull at once is the reader's call rather than a fixed 100. -->
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

		<div v-show="tab === 'conversations'" class="flex-1 overflow-auto">
			<div v-if="!loading && !conversations.length" class="p-10 text-center text-sm text-gray-500">
				No conversations match those filters.
			</div>
			<table v-else class="w-full text-sm">
				<thead class="bg-gray-50 text-xs uppercase tracking-wide text-gray-500 sticky top-0">
					<tr>
						<th class="text-left font-medium px-6 py-2">Conversation</th>
						<th class="text-left font-medium px-3 py-2">Agent</th>
						<th class="text-left font-medium px-3 py-2">Status</th>
						<th class="text-right font-medium px-3 py-2">Messages</th>
						<th class="text-right font-medium px-3 py-2">Summaries</th>
						<th class="text-left font-medium px-3 py-2">Last activity</th>
						<th class="px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="c in conversations"
						:key="c.name"
						class="border-t hover:bg-gray-50 cursor-pointer"
						@click="open(c.name)"
					>
						<td class="px-6 py-2">
							<div class="text-gray-900 truncate max-w-md">{{ c.title }}</div>
							<div class="text-xs text-gray-400 font-mono">{{ c.name }}</div>
						</td>
						<td class="px-3 py-2 text-gray-600">{{ c.agent }}</td>
						<td class="px-3 py-2">
							<span class="px-2 py-0.5 rounded-full text-xs" :class="statusClass(c.status)">{{ c.status }}</span>
						</td>
						<td class="px-3 py-2 text-right tabular-nums text-gray-700">{{ c.messages }}</td>
						<td class="px-3 py-2 text-right tabular-nums" :class="c.summaries ? 'text-gray-700' : 'text-gray-300'">
							{{ c.summaries }}
						</td>
						<td class="px-3 py-2 text-gray-500 text-xs">{{ c.last_activity || "—" }}</td>
						<td class="px-3 py-2 text-right">
							<span v-if="c.has_state" class="text-xs text-gray-400" title="Has a session scratchpad">state</span>
						</td>
					</tr>
				</tbody>
			</table>

			<div v-if="conversations.length" class="flex items-center justify-between border-t px-6 py-2 text-xs text-gray-500">
				<span>Showing {{ start + 1 }}–{{ start + conversations.length }} of {{ total }}</span>
				<span class="flex gap-2">
					<Button variant="subtle" :disabled="start === 0" @click="load(start - pageSize)">Previous</Button>
					<Button variant="subtle" :disabled="start + pageSize >= total" @click="load(start + pageSize)">Next</Button>
				</span>
			</div>
		</div>

		<!-- ── Retention ───────────────────────────────────────────────── -->
		<div v-show="tab === 'retention'" class="flex-1 overflow-auto p-6">
			<div class="grid grid-cols-1 xl:grid-cols-3 gap-6 items-start">
				<div class="xl:col-span-1 bg-white border rounded-lg p-6">
					<h2 class="text-sm font-semibold text-gray-900">Conversation retention</h2>
					<p class="text-xs text-gray-500 mt-1 mb-5">
						What happens to conversations nobody has touched for a while. Idle is measured from the newest
						message, not from when the record was last written — a status change or a title edit is not activity.
						An agent's own memory threads are never swept.
					</p>

					<div class="space-y-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Keep for (days)</label>
							<FormControl type="number" min="0" v-model.number="retention.ttl_days" class="w-40" />
							<p class="text-xs text-gray-500 mt-1">0 switches retention off — nothing is archived or deleted.</p>
						</div>

						<div v-if="retention.ttl_days > 0">
							<label class="block text-xs font-medium text-gray-700 mb-1">Then</label>
							<FormControl type="select" v-model="retention.archive_action" :options="actionOptions" class="w-56" />
							<p class="text-xs text-gray-500 mt-1">
								<span v-if="retention.archive_action === 'Delete'" class="text-red-600 font-medium">
									Delete removes the conversation and its messages permanently. It cannot be undone.
								</span>
								<span v-else>Archive marks the conversation and keeps everything, so it can be read and resumed.</span>
							</p>
						</div>

						<!-- The size of the thing before you switch it on, not after. -->
						<div v-if="retention.enabled" class="text-xs rounded-md px-3 py-2"
						     :class="retention.archive_action === 'Delete' ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-800'">
							The next nightly sweep would {{ retention.archive_action.toLowerCase() }}
							<strong>{{ retention.would_affect }}</strong>
							conversation{{ retention.would_affect === 1 ? "" : "s" }}.
						</div>

						<div class="flex items-center gap-3 pt-2">
							<Button variant="solid" :loading="saving" @click="saveRetention">Save</Button>
							<span v-if="savedAt" class="text-xs text-green-700">Saved.</span>
						</div>
					</div>
				</div>

			<div class="xl:col-span-2 bg-white border rounded-lg p-6">
				<div class="flex items-baseline justify-between gap-4">
					<h2 class="text-sm font-semibold text-gray-900">Compaction, per agent</h2>
					<span class="text-xs text-gray-500 shrink-0">
						{{ compactionOnCount }} of {{ agents.length }} switched on
					</span>
				</div>
				<p class="text-xs text-gray-500 mt-1 mb-4">
					Read-only here. Each agent's triggers are edited on its own AI Agent Task, in the Memory section
					of the task's configuration — this is the overview, so you can see what is switched on without
					opening six agents to find out.
				</p>
				<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead class="text-xs uppercase tracking-wide text-gray-500">
						<tr>
							<th class="text-left font-medium py-2">Agent</th>
							<th class="text-left font-medium py-2 px-3">Compaction</th>
							<th class="text-right font-medium py-2 px-3">Keep tail</th>
							<th class="text-right font-medium py-2 px-3">Token threshold</th>
							<th class="text-right font-medium py-2 px-3">Idle</th>
							<th class="text-center font-medium py-2 px-3">Each turn</th>
							<th class="text-left font-medium py-2 px-3">Summariser</th>
							<th class="text-right font-medium py-2">Context budget</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="a in agents" :key="a.name" class="border-t align-top"
						    :class="a.compaction_enabled ? '' : 'text-gray-400'">
							<td class="py-2 pr-3">
								<div class="text-gray-900">{{ a.chat_mode_label }}</div>
								<div class="text-xs text-gray-400 font-mono">{{ a.agent_id }}</div>
							</td>
							<td class="py-2 px-3">
								<span class="px-2 py-0.5 rounded-full text-xs whitespace-nowrap"
								      :class="a.compaction_enabled ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'">
									{{ a.compaction_enabled ? "On" : "Off" }}
								</span>
								<!-- Enabled with no trigger is a real trap: it looks configured and never fires. -->
								<div v-if="a.compaction_enabled && !hasTrigger(a)"
								     class="text-xs text-amber-700 mt-1 leading-tight">
									no trigger set — never fires
								</div>
							</td>
							<td class="py-2 px-3 text-right tabular-nums">{{ a.compaction_keep_tail || "—" }}</td>
							<td class="py-2 px-3 text-right tabular-nums">
								{{ a.compaction_token_threshold ? a.compaction_token_threshold.toLocaleString() : "—" }}
							</td>
							<td class="py-2 px-3 text-right tabular-nums whitespace-nowrap">
								{{ a.compaction_idle_minutes ? a.compaction_idle_minutes + "m" : "—" }}
							</td>
							<td class="py-2 px-3 text-center">
								<span v-if="a.compaction_on_task_boundary" class="text-green-700">Yes</span>
								<span v-else>—</span>
							</td>
							<td class="py-2 px-3 text-xs">
								<span v-if="a.compaction_model" class="font-mono">{{ a.compaction_model }}</span>
								<!-- No summariser named means the agent's own model does the summarising. -->
								<span v-else class="text-gray-400 italic">agent's own model</span>
							</td>
							<td class="py-2 text-right tabular-nums">
								{{ a.context_token_budget ? a.context_token_budget.toLocaleString() : "—" }}
							</td>
						</tr>
						<tr v-if="!agents.length">
							<td colspan="8" class="py-6 text-center text-sm text-gray-500">No enabled agents.</td>
						</tr>
					</tbody>
				</table>
				</div>
			</div>
			</div>
		</div>

		<!-- ── One conversation ────────────────────────────────────────── -->
		<Dialog v-model="showDetail" :options="{ size: '7xl', title: detail?.conversation?.title || 'Conversation' }">
			<template #body-content>
				<div v-if="detailLoading" class="py-10 text-center text-sm text-gray-500">Loading…</div>
				<div v-else-if="detail" class="space-y-5">
					<div class="grid grid-cols-4 gap-4 text-sm">
						<div>
							<div class="text-xs text-gray-500">Status</div>
							<span class="px-2 py-0.5 rounded-full text-xs" :class="statusClass(detail.conversation.status)">
								{{ detail.conversation.status }}
							</span>
						</div>
						<div><div class="text-xs text-gray-500">Agent</div>{{ detail.conversation.agent_mode }}</div>
						<div><div class="text-xs text-gray-500">Messages</div>{{ detail.conversation.messages }}</div>
						<div><div class="text-xs text-gray-500">Last activity</div>
							<span class="text-xs">{{ detail.conversation.last_activity || "—" }}</span>
						</div>
					</div>

					<div>
						<div class="flex items-center justify-between mb-2">
							<h3 class="text-sm font-semibold text-gray-900">
								Stored summaries
								<span class="text-gray-400 font-normal">({{ detail.summaries.length }})</span>
							</h3>
							<Button size="sm" :loading="compacting" @click="compactNow">Compact now</Button>
						</div>
						<p v-if="compactNote" class="text-xs mb-2" :class="compactOk ? 'text-green-700' : 'text-amber-700'">
							{{ compactNote }}
						</p>
						<div v-if="!detail.summaries.length" class="text-sm text-gray-500 border rounded-md px-3 py-4">
							Nothing summarised yet. Everything this agent sends is still the conversation itself.
						</div>
						<div v-for="(s, i) in detail.summaries" :key="s.name"
						     class="border rounded-md p-3 mb-2" :class="i === 0 ? 'border-gray-300' : 'border-gray-200 opacity-70'">
							<div class="flex items-center gap-2 text-xs text-gray-500 mb-2">
								<span v-if="i === 0" class="px-1.5 py-0.5 bg-gray-900 text-white rounded">in use</span>
								<span v-else>superseded</span>
								<span>covers {{ s.covered_count }} messages</span>
								<span v-if="s.model">· {{ s.model }}</span>
								<span class="ml-auto">{{ s.creation }}</span>
							</div>
							<p class="text-sm text-gray-800 whitespace-pre-wrap">{{ s.summary }}</p>
						</div>
					</div>

					<div v-if="Object.keys(detail.state || {}).length">
						<h3 class="text-sm font-semibold text-gray-900 mb-2">
							Scratchpad <span class="text-gray-400 font-normal">(version {{ detail.state_version }})</span>
						</h3>
						<pre class="text-xs bg-gray-50 border rounded-md p-3 overflow-auto max-h-64">{{ prettyState }}</pre>
					</div>
				</div>
			</template>
		</Dialog>

		<ErrorMessage :message="error" class="m-6" />
	</div>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl, frappeRequest } from "frappe-ui";
import { computed, onMounted, ref } from "vue";

const API = "/api/method/one_bpmn.api.sessions_api.";

const tab = ref("conversations");
const loading = ref(false);
const saving = ref(false);
const savedAt = ref(false);
const error = ref("");

const conversations = ref([]);
const total = ref(0);
const start = ref(0);
// Reactive so the toolbar can change it. 200 is the endpoint's own cap, so the
// options stop there rather than asking for a page it will silently shrink.
const pageLength = ref(20);
const PAGE_SIZES = [
	{ label: "20", value: 20 },
	{ label: "50", value: 50 },
	{ label: "100", value: 100 },
	{ label: "200", value: 200 },
];
// The select hands back a string and the pager does arithmetic on this
// ("start + pageSize"), which would concatenate instead of adding.
const pageSize = computed(() => Number(pageLength.value) || 20);
const agents = ref([]);
const agentModes = ref([]);
const retention = ref({ ttl_days: 0, archive_action: "Archive", enabled: false, would_affect: 0 });

const filters = ref({ agent: "", status: "", search: "" });

const showDetail = ref(false);
const detail = ref(null);
const detailLoading = ref(false);
const compacting = ref(false);
const compactNote = ref("");
const compactOk = ref(false);

const tabs = computed(() => [
	{ key: "conversations", label: "Conversations", count: total.value || null },
	{ key: "retention", label: "Retention", count: null },
]);

// The first option names the filter, so the toolbar reads as a row of pills
// rather than four little labelled boxes — same as the Instances toolbar.
const agentOptions = computed(() => [
	{ label: "All agents", value: "" },
	...agentModes.value.map((a) => ({ label: a, value: a })),
]);
const statusOptions = [
	{ label: "Any status", value: "" },
	{ label: "Active", value: "Active" },
	{ label: "Idle", value: "Idle" },
	{ label: "Archived", value: "Archived" },
];
const actionOptions = [
	{ label: "Archive — keep everything, mark it", value: "Archive" },
	{ label: "Delete — remove it permanently", value: "Delete" },
];

const prettyState = computed(() => JSON.stringify(detail.value?.state || {}, null, 2));

const compactionOnCount = computed(() => agents.value.filter((a) => a.compaction_enabled).length);

function statusClass(s) {
	if (s === "Active") return "bg-green-50 text-green-700";
	if (s === "Archived") return "bg-gray-200 text-gray-600";
	return "bg-amber-50 text-amber-700";
}

function hasTrigger(a) {
	return Boolean(a.compaction_token_threshold || a.compaction_idle_minutes || a.compaction_on_task_boundary);
}

async function call(method, params) {
	return frappeRequest({ url: API + method, method: "POST", params: params || {} });
}

async function load(from = 0) {
	loading.value = true;
	error.value = "";
	try {
		const res = await call("list_conversations", {
			agent: filters.value.agent || undefined,
			status: filters.value.status || undefined,
			search: filters.value.search || undefined,
			start: Math.max(0, from),
			page_length: pageSize.value,
		});
		conversations.value = res.conversations || [];
		total.value = res.total || 0;
		start.value = res.start || 0;
		agentModes.value = res.agents || [];
		retention.value = res.retention || retention.value;
	} catch (e) {
		error.value = e.messages?.[0] || e.message || String(e);
	} finally {
		loading.value = false;
	}
}

function changePageSize() {
	// Back to the first page: the old offset means something different under a
	// new page size, and on a big jump it can land past the end of the results.
	load(0);
}

async function loadAgents() {
	try {
		agents.value = await call("agent_compaction_summary");
	} catch (e) {
		agents.value = [];
	}
}

async function open(name) {
	showDetail.value = true;
	detailLoading.value = true;
	detail.value = null;
	compactNote.value = "";
	try {
		detail.value = await call("conversation_detail", { conversation: name });
	} catch (e) {
		error.value = e.messages?.[0] || e.message || String(e);
		showDetail.value = false;
	} finally {
		detailLoading.value = false;
	}
}

async function compactNow() {
	if (!detail.value) return;
	compacting.value = true;
	compactNote.value = "";
	try {
		const res = await call("compact_now", { conversation: detail.value.conversation.name });
		compactOk.value = !!res.queued;
		compactNote.value = res.queued
			? "Queued. It runs in the background — reopen this in a moment to see the summary."
			: res.reason;
	} catch (e) {
		compactOk.value = false;
		compactNote.value = e.messages?.[0] || e.message || String(e);
	} finally {
		compacting.value = false;
	}
}

async function saveRetention() {
	saving.value = true;
	savedAt.value = false;
	error.value = "";
	try {
		retention.value = await call("save_retention", {
			ttl_days: retention.value.ttl_days || 0,
			archive_action: retention.value.archive_action || "Archive",
		});
		savedAt.value = true;
		setTimeout(() => (savedAt.value = false), 3000);
	} catch (e) {
		error.value = e.messages?.[0] || e.message || String(e);
	} finally {
		saving.value = false;
	}
}

onMounted(() => {
	load();
	loadAgents();
});
</script>
