<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-4 sm:px-6 py-4">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Agent Collaboration (A2A)</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						Who we may delegate to, who may call us, and what is in flight either way.
					</p>
				</div>
				<nav class="flex gap-1 bg-gray-100 rounded-lg p-1 max-w-full overflow-x-auto">
					<button
						v-for="t in tabs"
						:key="t.key"
						class="px-3 py-1.5 text-sm rounded-md transition-colors whitespace-nowrap"
						:class="tab === t.key ? 'bg-white shadow-sm font-medium text-gray-900' : 'text-gray-600 hover:text-gray-900'"
						@click="tab = t.key"
					>
						{{ t.label }}
						<span v-if="t.count !== null" class="ml-1 text-xs text-gray-400">{{ t.count }}</span>
					</button>
				</nav>
			</div>
		</header>

		<A2AReconcilerBanner v-if="can.administer" />

		<ErrorMessage v-if="error" :message="error" class="mx-4 sm:mx-6 mt-4" />

		<div v-if="!can.administer" class="m-6 text-sm text-gray-600">
			Administering agent collaboration needs the System Manager role.
		</div>

		<template v-else>
			<A2AOurAgents
				v-show="tab === 'ours'"
				v-model:agents="ourAgents"
				@count="counts.ours = $event"
				@error="error = $event"
			/>
			<A2ARemoteAgents
				v-show="tab === 'remotes'"
				@count="counts.remotes = $event"
				@error="error = $event"
			/>
			<A2AClients
				v-show="tab === 'clients'"
				:our-agents="ourAgents"
				@count="counts.clients = $event"
				@error="error = $event"
			/>
			<A2ATasks
				v-show="tab === 'tasks'"
				:filter-options="filterOptions"
				@count="counts.tasks = $event"
				@error="error = $event"
			/>
			<A2ADelegations
				v-show="tab === 'delegations'"
				:filter-options="filterOptions"
				@count="counts.delegations = $event"
				@error="error = $event"
				@options-stale="loadFilterOptions"
			/>
			<A2AClarifications
				v-show="tab === 'clarifications'"
				@count="counts.clarifications = $event"
				@error="error = $event"
			/>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue"
import { ErrorMessage, frappeRequest } from "frappe-ui"
import A2AClarifications from "@/components/A2A/A2AClarifications.vue"
import A2AClients from "@/components/A2A/A2AClients.vue"
import A2ADelegations from "@/components/A2A/A2ADelegations.vue"
import A2AOurAgents from "@/components/A2A/A2AOurAgents.vue"
import A2AReconcilerBanner from "@/components/A2A/A2AReconcilerBanner.vue"
import A2ARemoteAgents from "@/components/A2A/A2ARemoteAgents.vue"
import A2ATasks from "@/components/A2A/A2ATasks.vue"
import { A2A_API } from "@/utils/a2aApi"

const EMPTY_FILTER_OPTIONS = { statuses: [], doctypes: [], workers: [], task_agents: [] }

const tab = ref("ours")
const can = ref({ administer: false, read: false })
const error = ref("")
const ourAgents = ref([])
const filterOptions = ref(EMPTY_FILTER_OPTIONS)
const counts = reactive({ ours: 0, remotes: 0, clients: 0, tasks: 0, delegations: 0, clarifications: 0 })

const tabs = computed(() => [
	{ key: "ours", label: "Our agents", count: counts.ours || null },
	{ key: "remotes", label: "Remote agents", count: counts.remotes || null },
	{ key: "clients", label: "Clients", count: counts.clients || null },
	{ key: "tasks", label: "Tasks", count: counts.tasks || null },
	{ key: "delegations", label: "Delegations", count: counts.delegations || null },
	{ key: "clarifications", label: "Clarifications", count: counts.clarifications || null },
])

// Both the Tasks and Delegations filters are built from the rows that exist.
async function loadFilterOptions() {
	try {
		filterOptions.value = await frappeRequest({ url: A2A_API + "delegation_filter_options" })
	} catch {
		// Dropdowns that cannot load leave the lists themselves usable.
		filterOptions.value = EMPTY_FILTER_OPTIONS
	}
}

onMounted(async () => {
	can.value = (await frappeRequest({ url: A2A_API + "get_permissions" })) || can.value
	if (!can.value.administer) return
	await loadFilterOptions()
})
</script>
