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

		<!-- Our agents (what we publish) -->
		<div v-else-if="tab === 'ours'" class="flex-1 overflow-auto px-6 py-4">
			<div class="flex items-start justify-end gap-4 mb-3">
				<Button variant="solid" @click="openExposeDialog()">Expose an agent</Button>
			</div>
			<div v-if="loading.ours" class="text-sm text-gray-500">Loading…</div>
			<table v-else class="w-full text-sm bg-white rounded-lg overflow-hidden">
				<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
					<tr>
						<th class="px-4 py-2">Agent</th>
						<th class="px-4 py-2">Tags</th>
						<th class="px-4 py-2">Reachable by</th>
						<th class="px-4 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="a in ourAgents" :key="a.agent_id" class="border-t">
						<td class="px-4 py-2">
							<div class="font-medium text-gray-900">{{ a.agent_name }}</div>
							<div class="text-xs text-gray-500">{{ a.agent_id }} · {{ a.agent_type }}</div>
						</td>
						<td class="px-4 py-2">
							<span
								v-for="t in a.tags"
								:key="t"
								class="inline-block mr-1 mb-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-700"
							>
								{{ t }}
							</span>
							<span v-if="!a.tags.length" class="text-gray-400 text-xs">no tags</span>
						</td>
						<td class="px-4 py-2 text-gray-600">
							<span v-if="a.reachable_by.length">{{ a.reachable_by.join(", ") }}</span>
							<span v-else class="text-gray-400" title="Its card is public, but no approved client lists it">
								nobody outside
							</span>
						</td>
						<td class="px-4 py-2 text-right whitespace-nowrap">
							<!-- The menu closes on click, so the copy confirmation cannot live
							     on the item that triggered it. -->
							<span v-if="copied === a.agent_id" class="mr-2 text-xs text-green-600">
								Link copied
							</span>
							<Dropdown :options="ourAgentActions(a)" placement="right">
								<Button variant="ghost" icon="more-horizontal" aria-label="Actions" />
							</Dropdown>
						</td>
					</tr>
					<tr v-if="!ourAgents.length">
						<td colspan="4" class="px-4 py-6 text-center text-gray-500">
							No agents are exposed yet. Tick “Exposed over A2A” on an enabled, Live agent.
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Remote agents (outbound) -->
		<div v-else-if="tab === 'remotes'" class="flex-1 overflow-auto px-6 py-4">
			<div class="flex items-start justify-between gap-4 mb-3">
				<p class="text-sm text-gray-600">
					Our processes may delegate only to an entry that is enabled and approved. Fetch the
					card first — the card is what you are approving. Changing an endpoint sends the
					entry back to Draft.
				</p>
				<Button variant="solid" @click="openRemoteForm()">New remote agent</Button>
			</div>
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
							<Dropdown :options="remoteActions(r)" placement="right">
								<Button variant="ghost" icon="more-horizontal" aria-label="Actions" />
							</Dropdown>
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
			<div class="flex items-start justify-between gap-4 mb-3">
				<p class="text-sm text-gray-600">
					Every caller is one entry with its own key and its own list of agents. Approving
					issues the key; revoking stops that caller alone.
				</p>
				<Button variant="solid" @click="openClientForm()">New client</Button>
			</div>
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
							<Dropdown :options="clientActions(c)" placement="right">
								<Button variant="ghost" icon="more-horizontal" aria-label="Actions" />
							</Dropdown>
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
							<th class="px-4 py-2" title="The agent or caller that asked for this work">
								Delegated by
							</th>
							<th class="px-4 py-2" title="The agent doing the work">Handled by</th>
							<th class="px-4 py-2">State</th>
							<th class="px-4 py-2" title="Nesting depth / total handoffs in this chain">
								Depth / handoffs
							</th>
							<th class="px-4 py-2">Waiting on</th>
							<th class="px-4 py-2">Started</th>
						</tr>
					</thead>
					<tbody>
						<template v-for="t in a2aTasks" :key="t.name">
							<tr
								class="border-t cursor-pointer hover:bg-gray-50"
								@click="expandedTask = expandedTask === t.name ? '' : t.name"
							>
								<td class="px-4 py-2">
									<Badge :theme="directionTheme(t.direction)">{{ t.direction }}</Badge>
								</td>
								<td class="px-4 py-2 text-gray-600">{{ initiator(t) }}</td>
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
							<!-- The full story of one handoff. Click the row to open. -->
							<tr v-if="expandedTask === t.name" class="border-t bg-gray-50">
								<td colspan="7" class="px-6 py-4">
									<div class="grid gap-3 md:grid-cols-2 text-sm">
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">What was asked</div>
											<div class="text-gray-800 whitespace-pre-wrap">{{ taskBrief(t) || "—" }}</div>
										</div>
										<div>
											<div class="text-xs uppercase text-gray-400 mb-1">Answer</div>
											<div class="text-gray-800 whitespace-pre-wrap">
												{{ t.status_message || t.error_message || "no answer yet" }}
											</div>
										</div>
									</div>
									<div class="flex flex-wrap gap-x-6 gap-y-1 mt-4 text-xs text-gray-600">
										<span>
											Task:
											<a :href="`/app/a2a-task/${t.name}`" target="_blank" class="text-blue-600 hover:underline">{{ t.name }}</a>
										</span>
										<span v-if="t.instance">
											Doing the work:
											<router-link :to="`/processa/instances/${t.instance}`" class="text-blue-600 hover:underline">{{ t.instance }}</router-link>
										</span>
										<span v-if="t.caller_instance">
											Waiting for it:
											<router-link :to="`/processa/instances/${t.caller_instance}`" class="text-blue-600 hover:underline">{{ t.caller_instance }}</router-link>
										</span>
										<span v-if="t.task_execution_id">Chain: {{ t.task_execution_id }}</span>
										<span>Started: {{ t.creation }}</span>
										<span v-if="t.completed_at">Finished: {{ t.completed_at }}</span>
										<span v-if="t.deadline && !isTerminal(t.state)">Deadline: {{ t.deadline }}</span>
									</div>
								</td>
							</tr>
						</template>
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

		<Dialog v-model="exposeOpen" :options="{ title: 'Expose an agent over A2A' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-3">
					Exposing an agent lets other agents hand it work, and publishes its card. It does
					not let anyone outside call it — an approved client has to list it as well.
				</p>
				<div class="border rounded-lg divide-y max-h-64 overflow-auto">
					<div
						v-for="a in exposableCandidates"
						:key="a.name"
						class="flex items-center justify-between gap-3 px-3 py-2"
					>
						<div>
							<div class="text-sm text-gray-900">{{ a.agent_name }}</div>
							<div class="text-xs text-gray-500">{{ a.agent_id }} · {{ a.agent_type }}</div>
						</div>
						<Button variant="subtle" :loading="saving" @click="expose(a)">Expose</Button>
					</div>
					<p v-if="!exposableCandidates.length" class="px-3 py-3 text-sm text-gray-500">
						Every enabled, Live agent is already exposed. An agent must be enabled and Live
						before it can take part at all.
					</p>
				</div>
				<ErrorMessage v-if="formError" :message="formError" class="mt-2" />
			</template>
		</Dialog>

		<Dialog v-model="tagsOpen" :options="{ title: 'Skill tags' }">
			<template #body-content>
				<FormControl
					label="Tags"
					v-model="tagsForm.skill_tags"
					placeholder="safety, assessment, triage"
					description="Comma separated. They appear on the public card and are how another agent recognises what this one is for."
				/>
				<ErrorMessage v-if="formError" :message="formError" class="mt-2" />
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveTags">Save</Button>
			</template>
		</Dialog>

		<Dialog v-model="remoteFormOpen" :options="{ title: remoteForm.name ? 'Edit remote agent' : 'New remote agent' }">
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl
						label="Name"
						v-model="remoteForm.agent_name"
						:disabled="!!remoteForm.name"
						placeholder="Partner Support Agent"
					/>
					<FormControl
						label="Endpoint URL"
						v-model="remoteForm.endpoint_url"
						placeholder="https://partner.example.com/a2a"
						description="Where its A2A endpoint lives. Changing this later sends the entry back to Draft."
					/>
					<FormControl
						type="select"
						label="Auth scheme"
						v-model="remoteForm.auth_scheme"
						:options="authSchemes"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme === 'API Key Header'"
						label="Auth header name"
						v-model="remoteForm.auth_header_name"
						placeholder="Authorization"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme !== 'None'"
						type="password"
						label="Credential"
						v-model="remoteForm.credential"
						description="Stored encrypted and read only when a call is made."
					/>
					<div class="grid grid-cols-2 gap-3">
						<FormControl label="Request timeout (s)" v-model="remoteForm.request_timeout" placeholder="30" />
						<FormControl label="Task deadline (min)" v-model="remoteForm.default_task_timeout_minutes" placeholder="240" />
						<FormControl label="Poll base (s)" v-model="remoteForm.poll_base_interval" placeholder="60" />
						<FormControl label="Poll max (s)" v-model="remoteForm.poll_max_interval" placeholder="900" />
					</div>
					<FormControl
						type="checkbox"
						label="Allow internal hosts"
						v-model="remoteForm.allow_internal_hosts"
						description="Only for pointing at this site itself. Leave off for real partners."
					/>
					<ErrorMessage v-if="formError" :message="formError" />
					<p class="text-xs text-gray-500">
						Saved as Draft. Fetch its card and approve it before any process can use it.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveRemote">
					{{ remoteForm.name ? "Save" : "Create" }}
				</Button>
			</template>
		</Dialog>

		<Dialog v-model="clientFormOpen" :options="{ title: 'New client' }">
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl label="Name" v-model="clientForm.client_name" placeholder="Partner A" />
					<FormControl
						type="textarea"
						label="Description"
						v-model="clientForm.description"
						placeholder="Who this caller is, and why they have access."
					/>
					<div>
						<div class="text-xs text-gray-600 mb-1">May call these agents</div>
						<AgentPicker v-model="clientForm.allowed_agents" :agents="ourAgents" />
					</div>
					<ErrorMessage v-if="formError" :message="formError" />
					<p class="text-xs text-gray-500">
						Saved as Draft. Approving it creates its service user and issues the key.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveClient">Create</Button>
			</template>
		</Dialog>

		<Dialog v-model="clientAgentsOpen" :options="{ title: 'Which agents this client may call' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-2">
					Takes effect immediately — the door reads this list on every call. Only exposed
					agents can be granted.
				</p>
				<AgentPicker v-model="agentsForm.allowed_agents" :agents="ourAgents" />
				<ErrorMessage v-if="formError" :message="formError" class="mt-2" />
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveClientAgents">Save</Button>
			</template>
		</Dialog>

		<Dialog v-model="cardOpen" :options="{ title: 'Agent card', size: '2xl' }">
			<template #body-content>
				<div v-if="openCard">
					<p class="text-sm text-gray-600 mb-2">
						This is exactly what an unauthenticated fetch of the card URL returns. It is
						generated from the configuration each time, so it cannot fall out of date.
					</p>
					<div class="text-xs text-gray-500 mb-3 break-all">
						<div class="mb-1"><span class="text-gray-400">Card:</span> {{ openCard.card_url }}</div>
						<div><span class="text-gray-400">Tasks:</span> {{ openCard.rpc_url }}</div>
					</div>
					<pre class="bg-gray-100 rounded p-3 text-xs overflow-auto max-h-96">{{ JSON.stringify(openCard.card, null, 2) }}</pre>
				</div>
			</template>
		</Dialog>

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
import { Badge, Button, Dialog, Dropdown, ErrorMessage, FormControl, frappeRequest } from "frappe-ui"
import AgentPicker from "@/components/a2a/AgentPicker.vue"

const API = "/api/method/one_bpmn.api.a2a_admin_api."
const TERMINAL = ["completed", "canceled", "failed", "rejected", "timed-out"]

const tab = ref("ours")
const can = ref({ administer: false, read: false })
const loading = reactive({ ours: false, remotes: false, clients: false, tasks: false })
const error = ref("")

const ourAgents = ref([])
const remotes = ref([])
const clients = ref([])
const a2aTasks = ref([])
const total = ref(0)
const start = ref(0)
const pageLength = ref(50)

const filters = reactive({ direction: "", state: "" })
const cardOpen = ref(false)
const openCard = ref(null)
const copied = ref("")
const credentialsOpen = ref(false)
const credentials = ref({ api_key: "", api_secret: "" })

const tabs = computed(() => [
	{ key: "ours", label: "Our agents", count: ourAgents.value.length || null },
	{ key: "remotes", label: "Remote agents", count: remotes.value.length || null },
	{ key: "clients", label: "Clients", count: clients.value.length || null },
	{ key: "tasks", label: "Tasks", count: total.value || null },
])

// Internal — one of our agents handing work to another on this site — is the
// most common direction, so it has to be filterable like the other two.
const directionOptions = [
	{ label: "All directions", value: "" },
	{ label: "Internal (same site)", value: "Internal" },
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

function directionTheme(direction) {
	if (direction === "Inbound") return "blue"
	if (direction === "Outbound") return "green"
	return "gray" // Internal — never crossed a trust boundary
}

const expandedTask = ref("")

function taskBrief(task) {
	// The instruction the caller sent, stored as JSON on the row.
	try {
		const payload = JSON.parse(task.request_payload || "{}")
		return payload.instruction || payload.text || ""
	} catch (e) {
		return task.request_payload || ""
	}
}

function initiator(task) {
	// Who asked for the work. An Internal hop has no client and no remote
	// agent — its initiator is the delegating agent, which is exactly the
	// case the old client-or-remote fallback rendered as a dash.
	return task.delegated_by || task.client || task.remote_agent || "—"
}



// ── Exposing an agent from here (WI-001934) ─────────────────────────────────
const exposeOpen = ref(false)
const tagsOpen = ref(false)
const exposable = ref([])
const tagsForm = ref({ agent: "", skill_tags: "" })

// Candidates are the ones not yet exposed; the table above already shows the rest.
const exposableCandidates = computed(() => exposable.value.filter((a) => !a.a2a_exposed))

async function loadExposable() {
	try {
		exposable.value = (await call("exposable_agents")) || []
	} catch (e) {
		error.value = e.message || String(e)
	}
}

async function openExposeDialog() {
	formError.value = ""
	await loadExposable()
	exposeOpen.value = true
}

async function expose(agent) {
	formError.value = ""
	saving.value = true
	try {
		await call("set_agent_exposure", { agent: agent.name, exposed: 1 })
		await Promise.all([loadOurAgents(), loadExposable()])
		if (!exposableCandidates.value.length) exposeOpen.value = false
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

async function unexpose(agent) {
	error.value = ""
	try {
		await call("set_agent_exposure", { agent: agent.name, exposed: 0 })
		await loadOurAgents()
	} catch (e) {
		error.value = e.message || String(e)
	}
}

function openTagsDialog(agent) {
	formError.value = ""
	tagsForm.value = { agent: agent.name, skill_tags: (agent.tags || []).join(", ") }
	tagsOpen.value = true
}

async function saveTags() {
	formError.value = ""
	saving.value = true
	try {
		await call("set_agent_exposure", {
			agent: tagsForm.value.agent,
			skill_tags: tagsForm.value.skill_tags,
		})
		tagsOpen.value = false
		await loadOurAgents()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

// ── Registering and editing (WI-001934) ─────────────────────────────────────
const authSchemes = [
	{ label: "None", value: "None" },
	{ label: "Bearer", value: "Bearer" },
	{ label: "API Key Header", value: "API Key Header" },
]
const saving = ref(false)
const formError = ref("")
const remoteFormOpen = ref(false)
const clientFormOpen = ref(false)
const clientAgentsOpen = ref(false)
const remoteForm = ref(blankRemote())
const clientForm = ref({ client_name: "", description: "", allowed_agents: [] })
const agentsForm = ref({ name: "", allowed_agents: [] })

function blankRemote() {
	return {
		name: "",
		agent_name: "",
		endpoint_url: "",
		auth_scheme: "None",
		auth_header_name: "Authorization",
		credential: "",
		allow_internal_hosts: false,
		request_timeout: "",
		default_task_timeout_minutes: "",
		poll_base_interval: "",
		poll_max_interval: "",
	}
}

function openRemoteForm(remote) {
	formError.value = ""
	remoteForm.value = remote
		? {
				...blankRemote(),
				name: remote.name,
				agent_name: remote.agent_name,
				endpoint_url: remote.endpoint_url,
				auth_scheme: remote.auth_scheme || "None",
				allow_internal_hosts: Boolean(remote.allow_internal_hosts),
				request_timeout: remote.request_timeout || "",
				default_task_timeout_minutes: remote.default_task_timeout_minutes || "",
				poll_base_interval: remote.poll_base_interval || "",
				poll_max_interval: remote.poll_max_interval || "",
			}
		: blankRemote()
	remoteFormOpen.value = true
}

async function saveRemote() {
	formError.value = ""
	saving.value = true
	const f = remoteForm.value
	const payload = {
		endpoint_url: f.endpoint_url,
		auth_scheme: f.auth_scheme,
		auth_header_name: f.auth_header_name,
		allow_internal_hosts: f.allow_internal_hosts ? 1 : 0,
		request_timeout: f.request_timeout || undefined,
		default_task_timeout_minutes: f.default_task_timeout_minutes || undefined,
		poll_base_interval: f.poll_base_interval || undefined,
		poll_max_interval: f.poll_max_interval || undefined,
	}
	// An empty credential on edit means "leave the stored one alone".
	if (f.credential) payload.credential = f.credential
	try {
		if (f.name) {
			await call("update_remote_agent", { name: f.name, ...payload })
		} else {
			await call("create_remote_agent", { agent_name: f.agent_name, ...payload })
		}
		remoteFormOpen.value = false
		await loadRemotes()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

function openClientForm() {
	formError.value = ""
	clientForm.value = { client_name: "", description: "", allowed_agents: [] }
	clientFormOpen.value = true
}

async function saveClient() {
	formError.value = ""
	saving.value = true
	try {
		await call("create_client", {
			client_name: clientForm.value.client_name,
			description: clientForm.value.description,
			allowed_agents: JSON.stringify(clientForm.value.allowed_agents),
		})
		clientFormOpen.value = false
		await loadClients()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

function openClientAgents(client) {
	formError.value = ""
	agentsForm.value = { name: client.name, allowed_agents: [...(client.allowed_agents || [])] }
	clientAgentsOpen.value = true
}

async function saveClientAgents() {
	formError.value = ""
	saving.value = true
	try {
		await call("set_client_agents", {
			name: agentsForm.value.name,
			allowed_agents: JSON.stringify(agentsForm.value.allowed_agents),
		})
		clientAgentsOpen.value = false
		await loadClients()
	} catch (e) {
		formError.value = e.message || String(e)
	} finally {
		saving.value = false
	}
}

async function call(method, params) {
	return await frappeRequest({ url: API + method, params })
}

async function loadOurAgents() {
	loading.ours = true
	try {
		ourAgents.value = (await call("list_agent_cards")) || []
	} catch (e) {
		error.value = e.message || String(e)
	} finally {
		loading.ours = false
	}
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

// ── Row actions ──────────────────────────────────────────────────────────────
// One menu per row rather than a rank of ghost buttons. Four repeated words on
// every line read as a wall and made the data itself hard to scan, which is
// what these tables are for.
//
// Nothing is shown as disabled: a menu item that cannot be used is left out by
// `condition`, so what the menu offers is what will actually happen. The
// prerequisite is always sitting directly above it — you cannot approve a
// remote agent until you have fetched the card you would be approving.

function ourAgentActions(agent) {
	return [
		{ label: "View card", icon: "eye", onClick: () => showCard(agent) },
		{ label: "Copy card link", icon: "link", onClick: () => copyCardUrl(agent) },
		{ label: "Skill tags", icon: "tag", onClick: () => openTagsDialog(agent) },
		{ label: "Unexpose", icon: "eye-off", theme: "red", onClick: () => unexpose(agent) },
	]
}

function remoteActions(remote) {
	return [
		{ label: "Edit", icon: "edit-2", onClick: () => openRemoteForm(remote) },
		{ label: "Fetch card", icon: "download", onClick: () => fetchCard(remote) },
		{
			label: "Approve",
			icon: "check-circle",
			// Approving IS approving the card, so there is nothing to approve
			// until one has been fetched.
			condition: () => remote.approval_status !== "Approved" && !!remote.card_name,
			onClick: () => setRemote(remote, "Approved"),
		},
		{
			label: "Revoke",
			icon: "slash",
			theme: "red",
			condition: () => remote.approval_status === "Approved",
			onClick: () => setRemote(remote, "Revoked"),
		},
	]
}

function clientActions(client) {
	const approved = client.approval_status === "Approved"
	return [
		{ label: "Which agents it may call", icon: "users", onClick: () => openClientAgents(client) },
		{
			label: "Approve",
			icon: "check-circle",
			condition: () => !approved,
			onClick: () => setClient(client, "Approved"),
		},
		{
			label: "Credentials",
			icon: "key",
			// The key only exists once approval issued it.
			condition: () => approved,
			onClick: () => showCredentials(client),
		},
		{
			label: "Revoke",
			icon: "slash",
			theme: "red",
			condition: () => approved,
			onClick: () => setClient(client, "Revoked"),
		},
	]
}

function showCard(agent) {
	openCard.value = agent
	cardOpen.value = true
}

async function copyCardUrl(agent) {
	try {
		await navigator.clipboard.writeText(agent.card_url)
		copied.value = agent.agent_id
		setTimeout(() => (copied.value = ""), 1500)
	} catch (e) {
		error.value = "Could not copy the link — select it from the card view instead."
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
	await Promise.all([loadOurAgents(), loadRemotes(), loadClients(), loadTasks(0)])
})
</script>
