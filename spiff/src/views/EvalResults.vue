<template>
	<div class="er">
		<!-- ── header ─────────────────────────────────────────────────── -->
		<div class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between flex-wrap gap-3">
				<div>
					<h1 class="text-lg font-semibold text-gray-900">{{ __("Eval results") }}</h1>
					<p class="text-sm text-gray-500">
						{{ isSystemManager
							? __("Every check that has run, newest first")
							: __("Checks on the agents whose processes you own, newest first") }}
					</p>
				</div>
				<router-link to="/processa/evals" class="text-sm text-blue-600 hover:underline">
					{{ __("Suites and configuration") }}
				</router-link>
			</div>

			<!-- ── filters: the failures-only one is the daily read ─────── -->
			<div class="flex flex-wrap items-end gap-3 mt-4">
				<FormControl
					type="select"
					:label="__('Triggered by')"
					v-model="filters.triggered_by"
					:options="TRIGGERS"
					@change="load"
				/>
				<FormControl
					type="select"
					:label="__('Since')"
					v-model="filters.days"
					:options="WINDOWS"
					@change="load"
				/>
				<FormControl
					type="autocomplete"
					:label="__('Agent')"
					v-model="agentFilter"
					:options="agentOptions"
					@change="onAgentChange"
				/>
				<label class="flex items-center gap-2 text-sm text-gray-700 pb-2">
					<input type="checkbox" v-model="filters.failures_only" @change="load" />
					{{ __("Failures only") }}
				</label>
			</div>
		</div>

		<!-- ── results ────────────────────────────────────────────────── -->
		<div class="flex-1 overflow-auto px-6 py-4">
			<div v-if="loading" class="p-10 text-center text-sm text-gray-500">{{ __("Loading…") }}</div>

			<!-- an empty page has to say what would be here and how to get it -->
			<div v-else-if="!rows.length" class="er-empty">
				<p class="font-medium text-gray-700">{{ emptyTitle }}</p>
				<p class="text-sm text-gray-500 mt-2">
					{{ __("Scheduled checks appear here as they run:") }}
				</p>
				<ul class="text-sm text-gray-500 mt-2 space-y-1">
					<li>{{ __("Nightly sweep — suites whose CI Role is Nightly") }}</li>
					<li>{{ __("Online sample — agents carrying an Online Rubric suite") }}</li>
					<li>{{ __("Pull request — the smoke suites, on every PR touching agent code") }}</li>
				</ul>
			</div>

			<div v-else>
				<!-- how each agent has moved, which one run never tells you -->
				<div v-if="trends.length" class="er-trends">
					<div v-for="t in trends" :key="t.agent" class="er-trend">
						<span class="er-trend-agent">{{ t.agent }}</span>
						<span class="er-trend-series">
							<span
								v-for="(p, i) in t.points"
								:key="i"
								class="er-bar"
								:class="{ 'er-bar--bad': p.rate !== null && p.rate < 100 }"
								:style="{ height: barHeight(p.rate) }"
								:title="`${p.when} — ${p.rate === null ? __('not scored') : p.rate.toFixed(0) + '%'}`"
							/>
						</span>
						<span class="er-trend-last">{{ t.last }}</span>
					</div>
				</div>

				<div v-for="day in days" :key="day.label" class="er-day">
					<div class="er-day-head">{{ day.label }}</div>
					<div
						v-for="row in day.rows"
						:key="row.run"
						class="er-row"
						:class="{ 'er-row--bad': row.failure || row.status === 'Failed' }"
						@click="open(row)"
					>
						<span class="er-time">{{ timeOf(row.when) }}</span>
						<span class="er-trigger" :class="triggerClass(row.triggered_by)">{{ row.triggered_by }}</span>
						<span class="er-agent">{{ row.agent || row.suite || "—" }}</span>
						<span class="er-count">
							{{ row.passed }}/{{ row.total }}
							<span v-if="row.rate !== null" class="er-rate">{{ row.rate.toFixed(0) }}%</span>
						</span>
						<span class="er-cost">{{ row.cost ? formatCost(row.cost) : "—" }}</span>
						<span v-if="row.failure" class="er-why">
							<span class="er-why-subject">{{ row.failure_subject }}</span>
							{{ row.failure }}
						</span>
						<span v-else-if="row.stopped" class="er-why er-why--warn">{{ row.stopped }}</span>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
// Eval results (WI-002537) — what the checks found, ordered by time.
//
// The suites page is organised around what you configure; this one is
// organised around what happened, because those are different questions and
// the second is the one asked every morning. Read-only on purpose: the moment
// it grows a Run button it becomes another suites page.
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { FormControl, frappeRequest } from "frappe-ui";

const __ = window.__ && typeof window.__ === "function" ? window.__ : (s) => s;
const router = useRouter();

const TRIGGERS = [
	{ label: __("Everything"), value: "" },
	{ label: __("Nightly sweep"), value: "Nightly sweep" },
	{ label: __("Online sample"), value: "Online sample" },
	{ label: __("Pull request"), value: "Pull request" },
	{ label: __("By hand"), value: "By hand" },
];
const WINDOWS = [
	{ label: __("Last 7 days"), value: 7 },
	{ label: __("Last 14 days"), value: 14 },
	{ label: __("Last 30 days"), value: 30 },
];

const rows = ref([]);
const loading = ref(true);
const isSystemManager = ref(false);
const agentFilter = ref("");
const filters = reactive({ triggered_by: "", days: 7, agent: "", failures_only: false });

const agentOptions = computed(() => {
	const names = [...new Set(rows.value.map((r) => r.agent).filter(Boolean))].sort();
	return [{ label: __("Every agent"), value: "" }].concat(names.map((n) => ({ label: n, value: n })));
});

const emptyTitle = computed(() =>
	filters.failures_only
		? __("Nothing failed in this window.")
		: __("No checks have run in this window.")
);

// Grouped by day so a morning read starts at "today" rather than at a date column.
const days = computed(() => {
	const groups = new Map();
	for (const row of rows.value) {
		const key = (row.when || "").slice(0, 10);
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key).push(row);
	}
	return [...groups.entries()].map(([key, list]) => ({ label: dayLabel(key), rows: list }));
});

// One run at 92% says nothing; three nights of 100 → 96 → 88 says everything.
const trends = computed(() => {
	const byAgent = new Map();
	for (const row of [...rows.value].reverse()) {
		if (!row.agent || row.total === 0) continue;
		if (!byAgent.has(row.agent)) byAgent.set(row.agent, []);
		byAgent.get(row.agent).push({ rate: row.rate, when: timeOf(row.when) });
	}
	return [...byAgent.entries()]
		.filter(([, points]) => points.length > 1)
		.map(([agent, points]) => {
			const recent = points.slice(-12);
			const last = recent[recent.length - 1];
			return {
				agent,
				points: recent,
				last: last.rate === null ? __("not scored") : `${last.rate.toFixed(0)}%`,
			};
		});
});

function barHeight(rate) {
	if (rate === null) return "3px";
	return `${Math.max(3, Math.round((rate / 100) * 22))}px`;
}

function dayLabel(key) {
	if (!key) return "";
	const today = new Date().toISOString().slice(0, 10);
	const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
	if (key === today) return __("Today");
	if (key === yesterday) return __("Yesterday");
	return key;
}

function timeOf(when) {
	return (when || "").slice(11, 16);
}

function formatCost(value) {
	return value < 0.01 ? `<0.01` : value.toFixed(2);
}

function triggerClass(trigger) {
	return {
		"er-trigger--nightly": trigger === "Nightly sweep",
		"er-trigger--online": trigger === "Online sample",
		"er-trigger--pr": trigger === "Pull request",
	};
}

function onAgentChange(value) {
	filters.agent = typeof value === "string" ? value : value?.value || "";
	load();
}

function open(row) {
	router.push(`/processa/evals/run/${encodeURIComponent(row.run)}`);
}

async function load() {
	loading.value = true;
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.scheduled_results",
			params: {
				days: filters.days,
				triggered_by: filters.triggered_by,
				agent: filters.agent,
				failures_only: filters.failures_only ? 1 : 0,
			},
		});
		rows.value = res?.runs || [];
		isSystemManager.value = !!res?.is_system_manager;
	} catch (e) {
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<style scoped>
.er { display: flex; flex-direction: column; height: 100%; background: #f8f9fb; }

.er-empty { background: #fff; border: 1px solid #eceef3; border-radius: 8px; padding: 40px; text-align: center; }
.er-empty ul { list-style: none; padding: 0; }

.er-trends { display: flex; flex-wrap: wrap; gap: 18px; padding: 4px 2px 16px; }
.er-trend { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #6b7280; }
.er-trend-agent { font-weight: 500; color: #374151; }
.er-trend-series { display: flex; align-items: flex-end; gap: 2px; height: 22px; }
.er-bar { width: 4px; background: #93a9f5; border-radius: 1px; }
.er-bar--bad { background: #e0a458; }
.er-trend-last { font-variant-numeric: tabular-nums; }

.er-day { margin-bottom: 18px; }
.er-day-head {
	font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
	color: #9ca3af; margin: 0 0 6px 2px;
}
.er-row {
	display: grid;
	grid-template-columns: 48px 110px minmax(120px, 1fr) 92px 64px minmax(0, 2.2fr);
	gap: 12px; align-items: baseline;
	background: #fff; border: 1px solid #eceef3; border-radius: 6px;
	padding: 9px 12px; margin-bottom: 5px; cursor: pointer;
	font-size: 13px;
}
.er-row:hover { border-color: #cdd4e4; }
.er-row--bad { border-left: 3px solid #c0392b; }

.er-time { color: #9ca3af; font-variant-numeric: tabular-nums; }
.er-trigger { font-size: 11px; color: #6b7280; }
.er-trigger--nightly { color: #2f4fd0; }
.er-trigger--online { color: #156b52; }
.er-trigger--pr { color: #9a5b00; }
.er-agent { color: #111827; font-weight: 500; }
.er-count { font-variant-numeric: tabular-nums; color: #374151; }
.er-rate { color: #9ca3af; margin-left: 4px; }
.er-cost { font-variant-numeric: tabular-nums; color: #9ca3af; }
.er-why { color: #6b7280; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.er-why-subject { color: #374151; margin-right: 6px; }
.er-why--warn { color: #9a5b00; }

@media (max-width: 900px) {
	.er-row { grid-template-columns: 48px 100px 1fr; }
	.er-cost, .er-why { display: none; }
}
</style>
