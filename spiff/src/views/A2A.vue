<template>
	<div class="h-full flex flex-col bg-gray-50">
		<header class="bg-white border-b px-6 py-4">
			<div class="flex items-center justify-between">
				<div>
					<h1 class="text-xl font-semibold text-gray-900">Agent Collaboration (A2A)</h1>
					<p class="text-xs text-gray-500 mt-0.5">
						Who we may delegate to, who may call us, and what is in flight either way.
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

		<ErrorMessage v-if="error" :message="error" class="mx-6 mt-4" />

		<div v-if="!can.administer" class="m-6 text-sm text-gray-600">
			Administering agent collaboration needs the System Manager role.
		</div>

		<!-- Remote agents (outbound) -->
		<div v-else-if="tab === 'remotes'" class="flex-1 overflow-auto px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Our processes may delegate only to an entry that is enabled and approved. Fetch the
				card first — the card is what you are approving. Changing an endpoint sends the
				entry back to Draft.
			</p>
			<div v-if="loading.remotes" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Agent</th>
						<th class="px-4 py-2">Endpoint</th>
						<th class="px-4 py-2">Card</th>
						<th class="px-4 py-2">Status</th>
						<th class="px-4 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in remotes" :key="r.name" class="border-t">
						<td class="px-4 py-2 font-medium text-gray-900">
							{{ r.agent_name }}
							<span v-if="!r.enabled" class="ml-1 text-xs text-gray-400">(disabled)</span>
						</td>
						<td class="px-4 py-2 text-gray-600 truncate max-w-xs">{{ r.endpoint_url }}</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="r.card_name">{{ r.card_name }}</span>
							<span v-else class="text-gray-400">not fetched</span>
						</td>
						<td class="px-4 py-2">
							<Badge :theme="statusTheme(r.approval_status)">{{ r.approval_status }}</Badge>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<Button variant="ghost" @click="fetchCard(r)">Fetch card</Button>
							<Button
								v-if="r.approval_status !== 'Approved'"
								variant="ghost"
								:disabled="!r.card_name"
								@click="setRemote(r, 'Approved')"
							>
								Approve
							</Button>
							<Button v-else variant="ghost" @click="setRemote(r, 'Revoked')">Revoke</Button>
						</td>
					</tr>
					<tr v-if="!remotes.length">
						<td colspan="5" class="px-4 py-6 text-center text-gray-500">
							No remote agents registered yet.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Clients (inbound) -->
		<div v-else-if="tab === 'clients'" class="flex-1 overflow-auto px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Every caller is one entry with its own key and its own list of agents. Approving
				issues the key; revoking stops that caller alone.
			</p>
			<div v-if="loading.clients" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Client</th>
						<th class="px-4 py-2">Service user</th>
						<th class="px-4 py-2">May call</th>
						<th class="px-4 py-2">Status</th>
						<th class="px-4 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="c in clients" :key="c.name" class="border-t">
						<td class="px-4 py-2 font-medium text-gray-900">
							{{ c.client_name }}
							<span v-if="!c.enabled" class="ml-1 text-xs text-gray-400">(disabled)</span>
						</td>
						<td class="px-4 py-2 text-gray-600">
							{{ c.user || "—" }}
						</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="c.allowed_agents.length">{{ c.allowed_agents.join(", ") }}</span>
							<span v-else class="text-gray-400">nothing</span>
						</td>
						<td class="px-4 py-2">
							<Badge :theme="statusTheme(c.approval_status)">{{ c.approval_status }}</Badge>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<Button
								v-if="c.approval_status !== 'Approved'"
								variant="ghost"
								@click="setClient(c, 'Approved')"
							>
								Approve
							</Button>
							<template v-else>
								<Button variant="ghost" @click="showCredentials(c)">Credentials</Button>
								<Button variant="ghost" @click="setClient(c, 'Revoked')">Revoke</Button>
							</template>
						</td>
					</tr>
					<tr v-if="!clients.length">
						<td colspan="5" class="px-4 py-6 text-center text-gray-500">
							No clients registered yet.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Task monitor -->
		<template v-else>
			<div class="bg-white px-6 py-3 border-b flex flex-wrap gap-4 items-center">
				<FormControl
					type="select"
					v-model="filters.direction"
					:options="directionOptions"
					class="w-44"
					@change="loadTasks(0)"
				/>
				<FormControl
					type="select"
					v-model="filters.state"
					:options="stateOptions"
					class="w-48"
					@change="loadTasks(0)"
				/>
				<Button v-if="filters.direction || filters.state" variant="ghost" @click="resetFilters">
					Clear filters
				</Button>
				<div class="ml-auto text-sm text-gray-600">{{ total }} tasks</div>
			</div>
			<div class="flex-1 overflow-auto px-6 py-4">
				<div v-if="loading.tasks" class="text-sm text-gray-500">Loading…</div>
				<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Direction</th>
							<th class="px-4 py-2">Who</th>
							<th class="px-4 py-2">Agent</th>
							<th class="px-4 py-2">State</th>
							<th class="px-4 py-2" title="Nesting depth / total handoffs in this chain">
								Depth / handoffs
							</th>
							<th class="px-4 py-2">Waiting on</th>
							<th class="px-4 py-2">Started</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="t in a2aTasks" :key="t.name" class="border-t">
							<td class="px-4 py-2">
								<Badge :theme="t.direction === 'Inbound' ? 'blue' : 'green'">
									{{ t.direction }}
								</Badge>
							</td>
							<td class="px-4 py-2 text-gray-600">{{ t.client || t.remote_agent || "—" }}</td>
							<td class="px-4 py-2 text-gray-600">{{ t.agent_configuration || "—" }}</td>
							<td class="px-4 py-2">
								<Badge :theme="stateTheme(t.state)">{{ t.state }}</Badge>
								<div v-if="t.error_message" class="text-xs text-red-600 mt-0.5">
									{{ t.error_message }}
								</div>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ t.delegation_depth }} / {{ t.handoff_count }}
							</td>
							<td class="px-4 py-2 text-gray-600 text-xs">
								<span v-if="t.pending_human_task">a person</span>
								<span v-else-if="t.next_poll_at && !isTerminal(t.state)">
									next check {{ t.next_poll_at }}
								</span>
								<span v-else class="text-gray-400">—</span>
							</td>
							<td class="px-4 py-2 text-gray-500 text-xs">{{ t.creation }}</td>
						</tr>
						<tr v-if="!a2aTasks.length">
							<td colspan="7" class="px-4 py-6 text-center text-gray-500">
								No tasks yet.
							</td>
						</tr>
					</tbody>
				</table>
				<div v-if="total > pageLength" class="flex items-center justify-between mt-3">
					<Button variant="ghost" :disabled="start === 0" @click="loadTasks(start - pageLength)">
						Previous
					</Button>
					<span class="text-xs text-gray-500">
						{{ start + 1 }}–{{ Math.min(start + pageLength, total) }} of {{ total }}
					</span>
					<Button
						variant="ghost"
						:disabled="start + pageLength >= total"
						@click="loadTasks(start + pageLength)"
					>
						Next
					</Button>
				</div>
			</div>
		</template>

		<Dialog v-model="credentialsOpen" :options="{ title: 'Client credentials' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-3">
					Hand these to the caller out of band. The secret is shown because it is
					decrypted on request — it is never stored on the client record.
				</p>
				<div class="text-sm">
					<div class="mb-2">
						<span class="text-gray-500">API key</span>
						<code class="block bg-gray-100 rounded px-2 py-1 mt-0.5">{{ credentials.api_key }}</code>
					</div>
					<div>
						<span class="text-gray-500">API secret</span>
						<code class="block bg-gray-100 rounded px-2 py-1 mt-0.5">{{ credentials.api_secret }}</code>
					</div>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// WI-001934: the A2A operation, in the SPA.
//
// Read-mostly. Approvals, card fetches and credential reads all call the
// modules that own those rules, so this screen cannot become a second
// implementation of them.
import { computed, onMounted, reactive, ref } from "vue"
import { Badge, Button, Dialog, ErrorMessage, FormControl, frappeRequest } from "frappe-ui"

const API = "/api/method/one_bpmn.api.a2a_admin_api."
const TERMINAL = ["completed", "canceled", "failed", "rejected", "timed-out"]

const tab = ref("remotes")
const can = ref({ administer: false, read: false })
const loading = reactive({ remotes: false, clients: false, tasks: false })
const error = ref("")

const remotes = ref([])
const clients = ref([])
const a2aTasks = ref([])
const total = ref(0)
const start = ref(0)
const pageLength = ref(50)

const filters = reactive({ direction: "", state: "" })
const credentialsOpen = ref(false)
const credentials = ref({ api_key: "", api_secret: "" })

const tabs = computed(() => [
	{ key: "remotes", label: "Remote agents", count: remotes.value.length || null },
	{ key: "clients", label: "Clients", count: clients.value.length || null },
	{ key: "tasks", label: "Tasks", count: total.value || null },
])

const directionOptions = [
	{ label: "All directions", value: "" },
	{ label: "Inbound", value: "Inbound" },
	{ label: "Outbound", value: "Outbound" },
]

const stateOptions = [
	{ label: "All states", value: "" },
	{ label: "submitted", value: "submitted" },
	{ label: "working", value: "working" },
	{ label: "input-required", value: "input-required" },
	{ label: "completed", value: "completed" },
	{ label: "failed", value: "failed" },
	{ label: "canceled", value: "canceled" },
	{ label: "timed-out", value: "timed-out" },
]

function isTerminal(state) {
	return TERMINAL.includes(state)
}

function statusTheme(status) {
	if (status === "Approved") return "green"
	if (status === "Revoked") return "red"
	return "gray"
}

function stateTheme(state) {
	if (state === "completed") return "green"
	if (["failed", "timed-out", "rejected"].includes(state)) return "red"
	if (state === "input-required") return "orange"
	if (state === "canceled") return "gray"
	return "blue"
}

async function call(method, params) {
	return await frappeRequest({ url: API + method, params })
}

async function loadRemotes() {
	loading.remotes = true
	try {
		remotes.value = (await call("list_remote_agents")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.remotes = false
	}
}

async function loadClients() {
	loading.clients = true
	try {
		clients.value = (await call("list_clients")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.clients = false
	}
}

async function loadTasks(from = 0) {
	loading.tasks = true
	try {
		const r = await call("list_tasks", {
			direction: filters.direction || undefined,
			state: filters.state || undefined,
			start: Math.max(0, from),
			page_length: pageLength.value,
		})
		a2aTasks.value = r.tasks || []
		total.value = r.total || 0
		start.value = r.start || 0
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.tasks = false
	}
}

function resetFilters() {
	filters.direction = ""
	filters.state = ""
	loadTasks(0)
}

async function fetchCard(remote) {
	error.value = ""
	try {
		await call("fetch_remote_card", { name: remote.name })
		await loadRemotes()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function setRemote(remote, status) {
	error.value = ""
	try {
		await call("set_remote_approval", { name: remote.name, approval_status: status })
		await loadRemotes()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function setClient(client, status) {
	error.value = ""
	try {
		await call("set_client_approval", { name: client.name, approval_status: status })
		await loadClients()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function showCredentials(client) {
	error.value = ""
	try {
		credentials.value = await call("get_client_credentials", { name: client.name })
		credentialsOpen.value = true
	} catch (e) {
		error.value = e.message || String(e)
	}
}

onMounted(async () => {
	can.value = (await call("get_permissions")) || can.value
	if (!can.value.administer) return
	await Promise.all([loadRemotes(), loadClients(), loadTasks(0)])
})
</script>
