<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="bg-white px-4 sm:px-6 py-3 border-b flex flex-wrap gap-3 items-center">
			<FormControl
				v-model="dFilters.a2a_task"
				type="text"
				placeholder="Task, e.g. A2A-17522"
				class="w-full sm:w-52"
			/>
			<FormControl
				v-model="dFilters.reference_doctype"
				type="select"
				:options="doctypeOptions"
				class="w-full sm:w-48"
				@change="loadDelegations(0)"
			/>
			<FormControl
				v-model="dFilters.reference_name"
				type="text"
				placeholder="Document, e.g. DOC-0028"
				class="w-full sm:w-52"
			/>
			<FormControl
				v-model="dFilters.status"
				type="select"
				:options="delegationStatusOptions"
				class="w-full sm:w-48"
				@change="loadDelegations(0)"
			/>
			<Button v-if="anyDelegationFilter" variant="ghost" @click="resetDelegationFilters">
				Clear filters
			</Button>
			<div class="ml-auto flex flex-wrap items-center gap-4">
				<span class="text-sm text-gray-600">{{ dTotal }} delegations</span>
				<A2APageSize v-model="dPageLength" @change="changeDelegationPageSize" />
			</div>
		</div>
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Who is working on what, and how far along. A delegation that stopped at a limit
				stays here with the limit that stopped it — click a row for the whole story.
			</p>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[56rem] text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Work</th>
							<th class="px-4 py-2" title="The agent that handed the work over">
								Delegated by
							</th>
							<th class="px-4 py-2" title="The agent doing the work">Handled by</th>
							<th class="px-4 py-2">Status</th>
							<th class="px-4 py-2" title="The limit that stopped it, if one did">
								Stopped at
							</th>
							<th class="px-4 py-2" title="Nesting depth / hand-offs / attempts">
								D / H / A
							</th>
							<th class="px-4 py-2">Last updated</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="d in delegations"
							:key="d.name"
							class="border-t cursor-pointer hover:bg-gray-50"
							@click="openDelegation(d)"
						>
							<td class="px-4 py-2">
								<div class="font-medium text-gray-900">
									{{ d.reference_name || "—" }}
								</div>
								<div class="text-xs text-gray-500">
									{{ d.reference_doctype || "nothing linked" }}
								</div>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ d.delegating_agent || "—" }}
							</td>
							<td class="px-4 py-2 text-gray-600">{{ d.worker_agent || "—" }}</td>
							<td class="px-4 py-2">
								<Badge :theme="delegationTheme(d.status)">{{ d.status }}</Badge>
							</td>
							<td class="px-4 py-2 text-gray-600 text-xs">
								<span v-if="d.cancelled_by">cancelled by a person</span>
								<span v-else-if="d.stopped_reason">
									{{ limitLabel(d.stopped_reason) }}
									<span v-if="d.limit_value" class="text-gray-400">
										({{ d.reached_value }}/{{ d.limit_value }})
									</span>
								</span>
								<span v-else class="text-gray-400">—</span>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ d.delegation_depth }} / {{ d.handoff_count }} /
								{{ d.attempt_count || 1 }}
							</td>
							<td class="px-4 py-2 text-gray-500 text-xs">{{ d.modified }}</td>
						</tr>
						<tr v-if="!delegations.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								{{
									anyDelegationFilter
										? "Nothing matches those filters."
										: "No delegations yet."
								}}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<A2APager
				:start="dStart"
				:count="delegations.length"
				:total="dTotal"
				:page-length="dPageLengthNum"
				@prev="prevDelegationPage"
				@next="nextDelegationPage"
			/>
		</div>
		<A2ADelegationModal
			v-model="delegationOpen"
			:row="openDelegationRow"
			:task="openDelegationTask"
			:title="openDelegationTitle"
			:loading="loadingDetail"
			@changed="onDelegationChanged"
			@error="emit('error', $event)"
		/>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { Badge, Button, FormControl, frappeRequest } from "frappe-ui";
import A2ADelegationModal from "@/components/Modals/A2ADelegationModal/A2ADelegationModal.vue";
import A2APageSize from "@/components/A2A/A2APageSize/A2APageSize.vue";
import A2APager from "@/components/A2A/A2APager/A2APager.vue";
import { useA2AList } from "@/composables/useA2AList";
import { A2A_API } from "@/utils/a2aApi";
import { delegationTheme, limitLabel } from "@/utils/a2aFormat";

const props = defineProps({
	filterOptions: { type: Object, required: true },
});
const emit = defineEmits(["error", "count", "options-stale"]);

const doctypeOptions = computed(() => [
	{ label: "All doctypes", value: "" },
	...props.filterOptions.doctypes.map((d) => ({ label: d, value: d })),
]);

const delegationStatusOptions = computed(() => [
	{ label: "All statuses", value: "" },
	...props.filterOptions.statuses.map((s) => ({ label: s, value: s })),
]);

const dFilters = reactive({ a2a_task: "", reference_doctype: "", reference_name: "", status: "" });
const anyDelegationFilter = computed(() =>
	Boolean(
		dFilters.a2a_task ||
		dFilters.reference_doctype ||
		dFilters.reference_name ||
		dFilters.status,
	),
);

const delegationOpen = ref(false);
const openDelegationRow = ref(null);
const openDelegationTask = ref(null);
const openDelegationTitle = ref("");
const loadingDetail = ref(false);

const {
	rows: delegations,
	total: dTotal,
	start: dStart,
	loading,
	pageLength: dPageLength,
	pageLengthNum: dPageLengthNum,
	load: loadDelegations,
	prev: prevDelegationPage,
	next: nextDelegationPage,
	changeSize: changeDelegationPageSize,
} = useA2AList({
	url: A2A_API + "list_delegations",
	rowsKey: "delegations",
	buildParams: () => ({
		a2a_task: dFilters.a2a_task || undefined,
		reference_doctype: dFilters.reference_doctype || undefined,
		reference_name: dFilters.reference_name || undefined,
		status: dFilters.status || undefined,
	}),
	onError: (message) => emit("error", message),
});

watch(dTotal, (n) => emit("count", n));

// The two name filters match on a fragment, so they search as you type (debounced).
let delegationTimer = null;
watch(
	() => [dFilters.a2a_task, dFilters.reference_name],
	() => {
		clearTimeout(delegationTimer);
		delegationTimer = setTimeout(() => loadDelegations(0), 300);
	},
);

function resetDelegationFilters() {
	dFilters.a2a_task = "";
	dFilters.reference_doctype = "";
	dFilters.reference_name = "";
	dFilters.status = "";
	loadDelegations(0);
}

async function openDelegation(row) {
	openDelegationRow.value = row;
	openDelegationTask.value = null;
	openDelegationTitle.value = "";
	delegationOpen.value = true;
	loadingDetail.value = true;
	try {
		const r = await frappeRequest({
			url: A2A_API + "delegation_detail",
			params: { name: row.name },
		});
		openDelegationRow.value = r.delegation || row;
		openDelegationTask.value = r.task || null;
		openDelegationTitle.value = r.reference_title || "";
	} catch (e) {
		emit("error", e.message || String(e));
	} finally {
		loadingDetail.value = false;
	}
}

async function onDelegationChanged(status) {
	openDelegationRow.value = { ...openDelegationRow.value, status };
	emit("options-stale");
	await loadDelegations(dStart.value);
}

onMounted(() => loadDelegations(0));
</script>
