<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<div class="flex items-center gap-3">
				<router-link to="/processa/evals" class="text-gray-400 hover:text-gray-600">
					<Icon icon="lucide:arrow-left" class="w-5 h-5" />
				</router-link>
				<h1 class="text-xl font-semibold text-gray-900">Response feedback</h1>
				<span class="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">
					What users said about your agents' replies
				</span>
			</div>
			<div class="flex items-center gap-2">
				<FormControl type="date" v-model="fromDate" class="w-36" />
				<span class="text-sm text-gray-400">to</span>
				<FormControl type="date" v-model="toDate" class="w-36" />
				<Button icon-left="refresh-cw" @click="refreshAll" :loading="loading">Refresh</Button>
			</div>
		</header>

		<main class="flex-1 p-6 overflow-auto space-y-6">
			<!-- Counts, always with their denominator. Never a satisfaction score:
			     under 1% of replies get rated and raters sit at the extremes, so an
			     average would be confidently wrong. -->
			<div class="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
				<div
					v-for="c in overviewCards"
					:key="c.key"
					class="bg-white rounded-lg shadow-sm p-4 border-l-4"
					:class="c.border"
				>
					<div class="text-xs text-gray-500 uppercase tracking-wide font-medium">{{ c.label }}</div>
					<div class="text-2xl font-bold text-gray-900">{{ c.value }}</div>
					<div v-if="c.hint" class="text-xs text-gray-400 mt-0.5">{{ c.hint }}</div>
				</div>
			</div>

			<!-- Filters -->
			<div class="bg-white rounded-lg shadow-sm p-4 flex flex-wrap items-end gap-3">
				<div class="w-44">
					<label class="block text-xs text-gray-600 mb-1.5">Rating</label>
					<FormControl type="select" :options="ratingOptions" v-model="rating" />
				</div>
				<div class="w-44">
					<label class="block text-xs text-gray-600 mb-1.5">Status</label>
					<FormControl type="select" :options="statusOptions" v-model="status" />
				</div>
				<div class="w-60">
					<label class="block text-xs text-gray-600 mb-1.5">Agent</label>
					<FormControl type="select" :options="agentOptions" v-model="agent" />
				</div>
				<Button v-if="notDefaultQueue" variant="ghost" @click="resetToQueue">
					Back to the triage queue
				</Button>
			</div>

			<!-- The queue -->
			<div class="bg-white rounded-lg shadow-sm overflow-hidden">
				<div class="px-6 py-3 border-b flex items-center justify-between">
					<h2 class="text-sm font-semibold text-gray-700">
						{{ listTitle }} <span class="text-gray-400 font-normal">({{ rows.length }})</span>
					</h2>
				</div>

				<div v-if="loading" class="p-6 space-y-3 animate-pulse">
					<div v-for="n in 3" :key="n" class="h-16 bg-gray-100 rounded"></div>
				</div>

				<!-- Empty is a sentence, not a blank table. -->
				<div v-else-if="loadError" class="p-10 text-center text-gray-500">
					<Icon icon="lucide:lock" class="w-8 h-8 mx-auto mb-2 text-gray-300" />
					<p class="text-sm">{{ loadError }}</p>
				</div>

				<div v-else-if="!rows.length" class="p-10 text-center text-gray-500">
					<Icon icon="lucide:message-square-dashed" class="w-8 h-8 mx-auto mb-2 text-gray-300" />
					<p v-if="overview.total_rated" class="text-sm">
						Nothing matches these filters. The queue is
						<button class="underline" @click="resetToQueue">negative and unreviewed</button>.
					</p>
					<template v-else>
						<p class="text-sm">Nobody has rated a reply yet.</p>
						<p class="text-xs mt-1 text-gray-400">
							Ratings appear when a user presses thumbs up or down in chat. An agent only
							shows those buttons when <strong>Collect Response Feedback</strong> is ticked
							on its AI Agent Configuration.
						</p>
					</template>
				</div>

				<table v-else class="w-full text-sm">
					<thead>
						<tr class="text-left text-xs uppercase tracking-wide text-gray-500 border-b">
							<th class="px-6 py-3 font-medium">What was said</th>
							<th class="px-6 py-3 font-medium w-40">Agent</th>
							<th class="px-6 py-3 font-medium w-32">Status</th>
							<th class="px-6 py-3 font-medium text-right w-72">Actions</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.name" class="border-b border-gray-100 align-top hover:bg-gray-50">
							<td class="px-6 py-3">
								<div class="flex items-start gap-2">
									<Icon
										:icon="r.rating === 'Negative' ? 'lucide:thumbs-down' : 'lucide:thumbs-up'"
										class="w-4 h-4 mt-0.5 shrink-0"
										:class="r.rating === 'Negative' ? 'text-red-500' : 'text-green-600'"
									/>
									<div class="min-w-0">
										<!-- The question first: a reply on its own cannot be judged. -->
										<div class="text-xs text-gray-500">
											<span class="font-medium">Asked:</span>
											{{ trim(r.prompt_text) || "—" }}
										</div>
										<div class="text-gray-900 mt-0.5">
											<span class="font-medium text-xs text-gray-500">Replied:</span>
											{{ trim(r.reply_text) || "—" }}
										</div>
										<div v-if="r.reasons.length" class="flex flex-wrap gap-1 mt-1.5">
											<span
												v-for="reason in r.reasons"
												:key="reason"
												class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-700"
											>
												{{ reason }}
											</span>
										</div>
										<!-- Someone's own words. Shown as written. -->
										<div v-if="r.comment" class="text-xs text-gray-600 mt-1.5 italic">
											“{{ r.comment }}”
										</div>
										<div class="text-xs text-gray-400 mt-1">
											{{ r.rated_by }} · {{ when(r.rated_on) }}
										</div>
									</div>
								</div>
							</td>
							<td class="px-6 py-3 text-gray-600">{{ r.agent_label || "—" }}</td>
							<td class="px-6 py-3">
								<span class="inline-block px-2 py-0.5 rounded-full text-xs" :class="statusPill(r.status)">
									{{ r.status }}
								</span>
							</td>
							<td class="px-6 py-3 text-right whitespace-nowrap">
								<template v-if="r.status === 'New'">
									<Button variant="ghost" :loading="busy[r.name]" @click="setStatus(r, 'Dismissed')">
										Dismiss
									</Button>
									<Button variant="subtle" :loading="busy[r.name]" @click="setStatus(r, 'Reviewed')">
										Mark reviewed
									</Button>
								</template>

								<template v-else-if="r.status === 'Reviewed'">
									<Button variant="ghost" :loading="busy[r.name]" @click="setStatus(r, 'Dismissed')">
										Dismiss
									</Button>
									<!-- Why it cannot be converted is answered by the server, so we
									     never offer a button that fails. -->
									<span v-if="!r.can_convert" class="text-xs text-gray-400 mr-2">
										{{ r.blocked_reason }}
									</span>
									<Button
										v-else
										variant="solid"
										icon-left="flask-conical"
										:loading="busy[r.name]"
										@click="convert(r)"
									>
										Create eval case
									</Button>
								</template>

								<Button
									v-if="r.eval_case"
									variant="ghost"
									icon-left="external-link"
									@click="openCase(r)"
								>
									Open eval case
								</Button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</main>
	</div>
</template>

<script setup>
// The triage queue for response feedback (WI-002068).
//
// One job: decide which complaints are real regressions, and turn those into
// tests. Everything on the page serves that decision — which is why the question
// is shown above the reply, why Dismiss sits beside Mark reviewed rather than
// hidden behind a menu, and why the counts never become a percentage.
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { Button, Dialog, FormControl, frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import dayjs from "dayjs";

const router = useRouter();

const loading = ref(false);
const rows = ref([]);
const overview = ref({});
const loadError = ref("");
const busy = reactive({});

const fromDate = ref(dayjs().subtract(29, "day").format("YYYY-MM-DD"));
const toDate = ref(dayjs().format("YYYY-MM-DD"));

// Defaults ARE the queue: negative and unreviewed is the only list anyone has to
// act on. Everything else is reachable, but nobody should have to filter their
// way to the work.
const rating = ref("Negative");
const status = ref("New");
const agent = ref("");

const ratingOptions = [
	{ label: "Negative", value: "Negative" },
	{ label: "Positive", value: "Positive" },
	{ label: "All ratings", value: "All" },
];
const statusOptions = [
	{ label: "New — awaiting review", value: "New" },
	{ label: "Reviewed", value: "Reviewed" },
	{ label: "Converted", value: "Converted" },
	{ label: "Dismissed", value: "Dismissed" },
	{ label: "All statuses", value: "All" },
];
const agentOptions = ref([{ label: "All agents", value: "" }]);

const fmt = new Intl.NumberFormat("en-US");

const overviewCards = computed(() => {
	const o = overview.value;
	const rated = o.total_rated ?? 0;
	const replies = o.total_replies ?? 0;
	const share = replies ? `${((rated / replies) * 100).toFixed(1)}% rated` : "no replies yet";
	return [
		{
			key: "rated",
			label: "Rated",
			value: `${fmt.format(rated)} of ${fmt.format(replies)}`,
			hint: share,
			border: "border-blue-500",
		},
		{ key: "negative", label: "Negative", value: fmt.format(o.negative ?? 0), border: "border-red-500" },
		{
			key: "queue",
			label: "Awaiting review",
			value: fmt.format(o.awaiting_review ?? 0),
			hint: "the work on this page",
			border: "border-amber-500",
		},
		{ key: "reviewed", label: "Reviewed", value: fmt.format(o.reviewed ?? 0), border: "border-indigo-500" },
		{ key: "converted", label: "Became tests", value: fmt.format(o.converted ?? 0), border: "border-green-500" },
	];
});

const notDefaultQueue = computed(
	() => rating.value !== "Negative" || status.value !== "New" || !!agent.value
);
const listTitle = computed(() =>
	notDefaultQueue.value ? "Feedback" : "Awaiting review"
);

function trim(text) {
	const t = (text || "").replace(/\s+/g, " ").trim();
	return t.length > 220 ? `${t.slice(0, 220)}…` : t;
}
function when(value) {
	return value ? dayjs(value).format("D MMM, HH:mm") : "";
}
function statusPill(value) {
	return (
		{
			New: "bg-amber-50 text-amber-700",
			Reviewed: "bg-indigo-50 text-indigo-700",
			Converted: "bg-green-50 text-green-700",
			Dismissed: "bg-gray-100 text-gray-500",
		}[value] || "bg-gray-100 text-gray-600"
	);
}

function resetToQueue() {
	rating.value = "Negative";
	status.value = "New";
	agent.value = "";
}

async function loadRows() {
	loading.value = true;
	loadError.value = "";
	try {
		rows.value =
			(await frappeRequest({
				url: "/api/method/one_bpmn.api.eval_api.list_response_feedback",
				params: {
					rating: rating.value,
					status: status.value,
					agent: agent.value || undefined,
					from_date: fromDate.value,
					to_date: toDate.value,
				},
			})) || [];
	} catch (e) {
		// A refusal is not an empty queue. Telling someone "nobody has rated a
		// reply yet" when the truth is "you may not look" is a lie the page can
		// very easily tell by accident.
		rows.value = [];
		loadError.value = /permission/i.test(String(e && (e.message || e.exc_type || e)))
			? "You do not have permission to read response feedback."
			: "Could not load feedback. Try refreshing.";
	} finally {
		loading.value = false;
	}
}

async function loadOverview() {
	try {
		overview.value =
			(await frappeRequest({
				url: "/api/method/one_bpmn.api.eval_api.get_feedback_overview",
				params: { from_date: fromDate.value, to_date: toDate.value, agent: agent.value || undefined },
			})) || {};
	} catch (e) {
		overview.value = {};
	}
}

async function loadAgents() {
	try {
		const list = (await frappeRequest({
			url: "/api/method/one_bpmn.api.eval_api.list_assignable_agents",
		})) || [];
		agentOptions.value = [
			{ label: "All agents", value: "" },
			// Every agent, Draft and Needs Attention included — this is a filter
			// over feedback that already exists, and feedback arrives against
			// agents long before they are Live.
			...list.map((a) => ({
				label:
					a.lifecycle_status && a.lifecycle_status !== "Live"
						? `${a.label || a.agent_name || a.name} — ${a.lifecycle_status}`
						: a.label || a.agent_name || a.name,
				value: a.name,
			})),
		];
	} catch (e) {
		/* the filter degrades to "All agents", never to a broken page */
	}
}

async function refreshAll() {
	await Promise.all([loadRows(), loadOverview()]);
}

async function setStatus(row, next) {
	busy[row.name] = true;
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.feedback.set_feedback_status",
			method: "POST",
			params: { feedback: row.name, status: next },
		});
		await refreshAll();
	} finally {
		busy[row.name] = false;
	}
}

async function convert(row) {
	busy[row.name] = true;
	try {
		// Reuses the endpoint that resolves the agent's "— Regressions" suite, so
		// a case never lands in the provisioned Baseline suite (which is wiped on
		// every re-provision).
		const out = await frappeRequest({
			url: "/api/method/one_bpmn.api.feedback.create_eval_case_from_feedback",
			method: "POST",
			params: { feedback: row.name },
		});
		await refreshAll();
		// Stay inside Processa. The reviewer's next job is to write what SHOULD
		// have happened, and the eval case editor lives on the suite page — so go
		// there with the case already open, rather than handing them off to the
		// desk mid-task.
		if (out && out.eval_case) goToCase(out.suite, out.eval_case);
	} finally {
		busy[row.name] = false;
	}
}

function openCase(row) {
	goToCase(row.eval_suite, row.eval_case);
}

function goToCase(suite, evalCase) {
	if (!evalCase) return;
	// Without the suite there is no Processa page that shows a case, so the desk
	// form is the only honest fallback — it should never happen, since every case
	// is created into a suite.
	if (!suite) {
		window.open(`/app/ai-eval-case/${encodeURIComponent(evalCase)}`, "_blank");
		return;
	}
	router.push({
		path: `/processa/evals/suite/${encodeURIComponent(suite)}`,
		query: { case: evalCase },
	});
}

watch([rating, status, agent, fromDate, toDate], refreshAll);
onMounted(async () => {
	await Promise.all([loadAgents(), refreshAll()]);
});
</script>
