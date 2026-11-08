<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="bg-white px-4 sm:px-6 py-3 border-b flex flex-wrap gap-3 items-center">
			<FormControl
				v-model="cFilters.agent_configuration"
				type="select"
				:options="clarificationAgentOptions"
				class="w-full sm:w-48"
				@change="loadClarifications(0)"
			/>
			<FormControl
				v-model="cFilters.owner_asked"
				type="select"
				:options="clarificationPeopleOptions"
				class="w-full sm:w-52"
				@change="loadClarifications(0)"
			/>
			<FormControl
				v-model="cFilters.reference_doctype"
				type="select"
				:options="clarificationDoctypeOptions"
				class="w-full sm:w-44"
				@change="loadClarifications(0)"
			/>
			<FormControl
				v-model="cFilters.status"
				type="select"
				:options="clarificationStatusOptions"
				class="w-full sm:w-44"
				@change="loadClarifications(0)"
			/>
			<div class="flex items-center gap-2">
				<span class="text-sm text-gray-600">Asked</span>
				<FormControl
					v-model="cFilters.asked_from"
					type="date"
					class="w-full sm:w-36"
					@change="loadClarifications(0)"
				/>
				<span class="text-sm text-gray-500">to</span>
				<FormControl
					v-model="cFilters.asked_to"
					type="date"
					class="w-full sm:w-36"
					@change="loadClarifications(0)"
				/>
			</div>
			<Button
				v-if="anyClarificationFilter"
				variant="ghost"
				@click="resetClarificationFilters"
			>
				Clear filters
			</Button>
			<div class="ml-auto flex flex-wrap items-center gap-4">
				<span class="text-sm text-gray-600">{{ cTotal }} questions</span>
				<A2APageSize v-model="cPageLength" @change="changeClarificationPageSize" />
			</div>
		</div>
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Where an agent stopped rather than guessed. A question still waiting is work that
				is not moving — click a row for the whole exchange.
			</p>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[56rem] text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">About</th>
							<th class="px-4 py-2" title="The agent that stopped and asked">
								Asked by
							</th>
							<th class="px-4 py-2" title="The person who set the requirement">
								Asked of
							</th>
							<th class="px-4 py-2">Question</th>
							<th class="px-4 py-2">Status</th>
							<th class="px-4 py-2">Asked</th>
							<th class="px-4 py-2">Last updated</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="c in clarifications"
							:key="c.name"
							class="border-t cursor-pointer hover:bg-gray-50"
							@click="openClarification(c)"
						>
							<td class="px-4 py-2">
								<div class="font-medium text-gray-900">
									{{ c.reference_name || "—" }}
								</div>
								<div class="text-xs text-gray-500">
									{{ c.reference_doctype || "nothing linked" }}
								</div>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ c.agent_configuration || "—" }}
							</td>
							<td class="px-4 py-2 text-gray-600">{{ c.owner_asked || "—" }}</td>
							<td class="px-4 py-2 text-gray-700">
								<div class="max-w-md truncate" :title="c.question">
									{{ c.question || "—" }}
								</div>
								<div v-if="c.round > 1" class="text-xs text-gray-500">
									round {{ c.round }}
								</div>
							</td>
							<td class="px-4 py-2">
								<Badge :theme="clarificationTheme(c)">{{
									clarificationLabel(c)
								}}</Badge>
							</td>
							<td class="px-4 py-2 text-gray-500 text-xs">{{ c.asked_at }}</td>
							<td class="px-4 py-2 text-gray-500 text-xs">{{ c.modified }}</td>
						</tr>
						<tr v-if="!clarifications.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								{{
									anyClarificationFilter
										? "Nothing matches those filters."
										: "No agent has needed to ask anything yet."
								}}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<A2APager
				:start="cStart"
				:count="clarifications.length"
				:total="cTotal"
				:page-length="cPageLengthNum"
				@prev="prevClarificationPage"
				@next="nextClarificationPage"
			/>
		</div>
		<A2AClarificationModal
			v-model="clarificationOpen"
			:row="openClarificationRow"
			:title="openClarificationTitle"
			:thread="clarificationThread"
			:loading="loadingDetail"
		/>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Badge, Button, FormControl, frappeRequest } from "frappe-ui";
import A2AClarificationModal from "@/components/A2A/A2AClarificationModal.vue";
import A2APageSize from "@/components/A2A/A2APageSize.vue";
import A2APager from "@/components/A2A/A2APager.vue";
import { useA2AList } from "@/composables/useA2AList";
import { CLARIFY_API } from "@/utils/a2aApi";
import { clarificationLabel, clarificationTheme } from "@/utils/a2aFormat";

const emit = defineEmits(["error", "count"]);

const EMPTY_OPTIONS = { agents: [], people: [], doctypes: [], statuses: [] };

const cFilters = reactive({
	agent_configuration: "",
	owner_asked: "",
	reference_doctype: "",
	status: "",
	asked_from: "",
	asked_to: "",
});
const clarificationOptions = ref(EMPTY_OPTIONS);
const clarificationOpen = ref(false);
const openClarificationRow = ref(null);
const openClarificationTitle = ref("");
const clarificationThread = ref([]);
const loadingDetail = ref(false);

const clarificationAgentOptions = computed(() => [
	{ label: "All agents", value: "" },
	...clarificationOptions.value.agents.map((a) => ({ label: a, value: a })),
]);
const clarificationPeopleOptions = computed(() => [
	{ label: "Asked of anyone", value: "" },
	...clarificationOptions.value.people.map((p) => ({ label: p, value: p })),
]);
const clarificationDoctypeOptions = computed(() => [
	{ label: "All doctypes", value: "" },
	...clarificationOptions.value.doctypes.map((d) => ({ label: d, value: d })),
]);
const clarificationStatusOptions = computed(() => [
	{ label: "Any status", value: "" },
	...clarificationOptions.value.statuses.map((s) => ({ label: s, value: s })),
]);

const anyClarificationFilter = computed(() => Object.values(cFilters).some(Boolean));

const {
	rows: clarifications,
	total: cTotal,
	start: cStart,
	loading,
	pageLength: cPageLength,
	pageLengthNum: cPageLengthNum,
	load: loadClarifications,
	prev: prevClarificationPage,
	next: nextClarificationPage,
	changeSize: changeClarificationPageSize,
} = useA2AList({
	url: CLARIFY_API + "list_clarifications",
	rowsKey: "clarifications",
	buildParams: () => ({
		agent_configuration: cFilters.agent_configuration || undefined,
		owner_asked: cFilters.owner_asked || undefined,
		reference_doctype: cFilters.reference_doctype || undefined,
		status: cFilters.status || undefined,
		asked_from: cFilters.asked_from || undefined,
		asked_to: cFilters.asked_to || undefined,
	}),
	onError: (message) => emit("error", message),
});

watch(cTotal, (n) => emit("count", n));

function resetClarificationFilters() {
	for (const key of Object.keys(cFilters)) cFilters[key] = "";
	loadClarifications(0);
}

async function openClarification(row) {
	openClarificationRow.value = row;
	openClarificationTitle.value = "";
	clarificationThread.value = [];
	clarificationOpen.value = true;
	loadingDetail.value = true;
	try {
		const r = await frappeRequest({
			url: CLARIFY_API + "clarification_detail",
			params: { name: row.name },
		});
		openClarificationRow.value = r.clarification || row;
		clarificationThread.value = r.thread || [];
		openClarificationTitle.value = r.reference_title || "";
	} catch (e) {
		emit("error", e.message || String(e));
	} finally {
		loadingDetail.value = false;
	}
}

async function loadClarificationOptions() {
	try {
		clarificationOptions.value = await frappeRequest({
			url: CLARIFY_API + "clarification_filter_options",
		});
	} catch {
		// Dropdowns that cannot load leave the list itself usable.
		clarificationOptions.value = EMPTY_OPTIONS;
	}
}

onMounted(() => {
	loadClarifications(0);
	loadClarificationOptions();
});
</script>
