<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Memory</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						What the agents have learned and kept. Yours and the shared ones; a System Manager sees
						everybody's.
					</p>
				</div>
				<Button :loading="loading" @click="load()">Refresh</Button>
			</div>
		</header>

		<!-- Filters across the top, matching Sessions and Instances. The options
		     come from the memories that actually exist, not from every value the
		     schema allows, so an empty choice is never offered. -->
		<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center">
			<FormControl type="select" v-model="filters.agent_element" :options="agentOptions" class="w-56" @change="load()" />
			<FormControl type="select" v-model="filters.user" :options="userOptions" class="w-52" @change="load()" />
			<FormControl type="select" v-model="filters.source_type" :options="sourceOptions" class="w-44" @change="load()" />
			<FormControl type="text" v-model="filters.search" placeholder="Search content" class="w-64" @change="load()" />
			<label class="flex items-center gap-2 text-sm text-gray-600 whitespace-nowrap">
				<input type="checkbox" v-model="filters.include_retired" class="rounded" @change="load()" />
				Show retired
			</label>

			<div class="flex items-center gap-2 ml-auto">
				<span class="text-sm text-gray-600 whitespace-nowrap">Page Size:</span>
				<FormControl type="select" v-model="pageLength" :options="PAGE_SIZES" class="w-20" @change="load()" />
			</div>
		</div>

		<ErrorMessage v-if="error" :message="error" class="mx-6 mt-3" />

		<div class="flex-1 overflow-auto">
			<div v-if="!loading && !memories.length" class="p-10 text-center text-sm text-gray-500">
				No memories match those filters.
			</div>
			<table v-else class="w-full text-sm">
				<thead class="bg-gray-50 text-xs uppercase tracking-wide text-gray-500 sticky top-0">
					<tr>
						<th class="text-left font-medium px-6 py-2">Memory</th>
						<th class="text-left font-medium px-3 py-2">Agent</th>
						<th class="text-left font-medium px-3 py-2">Belongs to</th>
						<th class="text-left font-medium px-3 py-2">Source</th>
						<th class="text-right font-medium px-3 py-2">Importance</th>
						<th class="text-right font-medium px-3 py-2">Confidence</th>
						<th class="text-left font-medium px-3 py-2">Last written</th>
						<th class="px-3 py-2"></th>
					</tr>
				</thead>
				<tbody class="divide-y">
					<tr
						v-for="m in memories"
						:key="m.name"
						class="hover:bg-gray-50 cursor-pointer"
						:class="m.retired ? 'opacity-60' : ''"
						@click="openDetail(m)"
					>
						<td class="px-6 py-2 max-w-lg">
							<div class="text-gray-900 truncate">{{ m.content }}</div>
							<div class="flex gap-2 mt-0.5">
								<span v-if="m.retired" class="text-xs text-gray-500">Retired</span>
								<span v-if="m.user_directed" class="text-xs text-blue-700">You asked for this</span>
								<span v-if="m.corroboration_count" class="text-xs text-gray-500">
									Confirmed {{ m.corroboration_count }}×
								</span>
							</div>
						</td>
						<td class="px-3 py-2 text-gray-600">{{ m.scope_key }}</td>
						<td class="px-3 py-2 text-gray-600">{{ m.owner_label }}</td>
						<td class="px-3 py-2 text-gray-600">{{ m.source_type }}</td>
						<td class="px-3 py-2 text-right text-gray-600">{{ m.importance }}</td>
						<td class="px-3 py-2 text-right text-gray-600">{{ Number(m.confidence).toFixed(2) }}</td>
						<td class="px-3 py-2 text-gray-600 whitespace-nowrap">{{ shortDate(m.modified) }}</td>
						<td class="px-3 py-2 text-right whitespace-nowrap" @click.stop>
							<Button v-if="!m.retired" size="sm" variant="subtle" :loading="busy === m.name" @click="retire(m)">
								Retire
							</Button>
							<Button v-else size="sm" variant="subtle" :loading="busy === m.name" @click="restore(m)">
								Restore
							</Button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<div class="bg-white border-t px-6 py-3 flex items-center justify-between text-sm text-gray-600">
			<span>{{ rangeLabel }}</span>
			<div class="flex gap-2">
				<Button variant="subtle" :disabled="start === 0" @click="load(start - pageLength)">Previous</Button>
				<Button variant="subtle" :disabled="start + pageLength >= total" @click="load(start + pageLength)">Next</Button>
			</div>
		</div>

		<!-- Detail as a panel on the right, not a new page: the filter you came
		     from stays on screen, so reading one memory does not cost you the
		     list you were working through. -->
		<div v-if="detail" class="fixed inset-0 z-40 flex justify-end" @click.self="detail = null">
			<div class="absolute inset-0 bg-black/20"></div>
			<aside class="relative w-[32rem] max-w-full h-full bg-white shadow-xl overflow-auto">
				<div class="px-6 py-4 border-b flex items-start justify-between gap-4">
					<div>
						<h2 class="text-sm font-semibold text-gray-900">Memory</h2>
						<p class="text-xs text-gray-500 mt-0.5">{{ detail.name }}</p>
					</div>
					<Button size="sm" variant="ghost" @click="detail = null">Close</Button>
				</div>

				<div class="px-6 py-4 space-y-5">
					<p class="text-sm text-gray-900 whitespace-pre-wrap">{{ detail.content }}</p>

					<div v-if="detail.retired" class="text-xs rounded-md px-3 py-2 bg-amber-50 text-amber-800">
						Retired, so it is no longer recalled. The record is kept and it can be put back.
					</div>

					<dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
						<div v-for="row in detailRows" :key="row.label">
							<dt class="text-xs text-gray-500">{{ row.label }}</dt>
							<dd class="text-gray-900">{{ row.value }}</dd>
						</div>
					</dl>

					<div v-if="detail.source_run">
						<div class="text-xs text-gray-500 mb-1">Came from</div>
						<a class="text-sm text-blue-700 hover:underline" :href="`/app/ai-agent-run/${detail.source_run}`" target="_blank">
							The run that produced it
						</a>
					</div>

					<div v-if="detail.metadata">
						<div class="text-xs text-gray-500 mb-1">Metadata</div>
						<pre class="text-xs bg-gray-50 rounded-md p-3 overflow-auto">{{ JSON.stringify(detail.metadata, null, 2) }}</pre>
					</div>

					<div class="pt-2 border-t flex items-center gap-3">
						<Button v-if="!detail.retired" variant="subtle" :loading="busy === detail.name" @click="retire(detail)">
							Retire
						</Button>
						<Button v-else variant="subtle" :loading="busy === detail.name" @click="restore(detail)">
							Restore
						</Button>
						<span class="text-xs text-gray-500">
							Retiring keeps the record and stops the agent using it.
						</span>
					</div>
				</div>
			</aside>
		</div>
	</div>
</template>

<script setup>
import { Button, ErrorMessage, FormControl, frappeRequest } from "frappe-ui";
import { computed, onMounted, reactive, ref } from "vue";

const API = "/api/method/one_bpmn.api.memory_api.";
const PAGE_SIZES = [
	{ label: "20", value: 20 },
	{ label: "50", value: 50 },
	{ label: "100", value: 100 },
];

const loading = ref(false);
const error = ref("");
const busy = ref("");
const memories = ref([]);
const total = ref(0);
const start = ref(0);
const pageLength = ref(20);
const detail = ref(null);
const options = ref({ agents: [], users: [], source_types: [] });

const filters = reactive({
	agent_element: "",
	user: "",
	source_type: "",
	search: "",
	include_retired: false,
});

function choices(label, values) {
	return [{ label, value: "" }, ...values.map((v) => ({ label: v, value: v }))];
}
const agentOptions = computed(() => choices("All agents", options.value.agents));
const userOptions = computed(() => choices("Everyone", options.value.users));
const sourceOptions = computed(() => choices("Any source", options.value.source_types));

const rangeLabel = computed(() => {
	if (!total.value) return "No memories";
	const to = Math.min(start.value + memories.value.length, total.value);
	return `${start.value + 1} to ${to} of ${total.value}`;
});

const detailRows = computed(() => {
	const d = detail.value;
	if (!d) return [];
	return [
		{ label: "Agent", value: d.scope_key || "None" },
		{ label: "Belongs to", value: d.owner_label },
		{ label: "Scope", value: d.memory_scope },
		{ label: "Source", value: d.source_type },
		{ label: "Importance", value: `${d.importance} of 5` },
		{ label: "Confidence", value: Number(d.confidence).toFixed(2) },
		{ label: "Confirmed", value: d.corroboration_count ? `${d.corroboration_count}×` : "Never" },
		{ label: "First written", value: shortDate(d.creation) },
		{ label: "Last written", value: shortDate(d.modified) },
	];
});

function shortDate(value) {
	if (!value) return "Never";
	return new Date(value.replace(" ", "T")).toLocaleString();
}

function call(method, params) {
	return frappeRequest({ url: API + method, method: "POST", params: params || {} });
}

async function load(from = 0) {
	loading.value = true;
	error.value = "";
	try {
		const r = await call("list_memories", {
			...filters,
			include_retired: filters.include_retired ? 1 : 0,
			start: Math.max(from, 0),
			page_length: pageLength.value,
		});
		memories.value = r.memories || [];
		total.value = r.total || 0;
		start.value = r.start || 0;
	} catch (e) {
		error.value = e.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function loadOptions() {
	try {
		options.value = await call("filter_options");
	} catch (e) {
		// A filter with no options is a smaller problem than a page that will
		// not open, so this never blocks the list.
	}
}

async function openDetail(m) {
	try {
		detail.value = await call("get_memory", { name: m.name });
	} catch (e) {
		error.value = e.message || String(e);
	}
}

async function act(method, m) {
	busy.value = m.name;
	error.value = "";
	try {
		await call(method, { name: m.name });
		await load(start.value);
		if (detail.value && detail.value.name === m.name) {
			detail.value = await call("get_memory", { name: m.name });
		}
	} catch (e) {
		error.value = e.message || String(e);
	} finally {
		busy.value = "";
	}
}

const retire = (m) => act("retire_memory", m);
const restore = (m) => act("restore_memory", m);

onMounted(() => {
	loadOptions();
	load();
});
</script>
