<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<div
				class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4 mb-3"
			>
				<p class="text-sm text-gray-600">
					Every caller is one entry with its own key and its own list of agents.
					Approving issues the key; revoking stops that caller alone.
				</p>
				<Button variant="solid" @click="openClientForm()">New client</Button>
			</div>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[44rem] text-sm bg-white rounded-lg overflow-hidden">
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
								<span v-if="!c.enabled" class="ml-1 text-xs text-gray-400"
									>(disabled)</span
								>
							</td>
							<td class="px-4 py-2 text-gray-600">
								{{ c.user || "—" }}
							</td>
							<td class="px-4 py-2 text-gray-600">
								<span v-if="c.allowed_agents.length">{{
									c.allowed_agents.join(", ")
								}}</span>
								<span v-else class="text-gray-400">nothing</span>
							</td>
							<td class="px-4 py-2">
								<Badge :theme="statusTheme(c.approval_status)">{{
									c.approval_status
								}}</Badge>
							</td>
							<td class="px-4 py-2 text-right whitespace-nowrap">
								<Button variant="ghost" @click="openClientAgents(c)"
									>Agents</Button
								>
								<Button
									v-if="c.approval_status !== 'Approved'"
									variant="ghost"
									@click="setClient(c, 'Approved')"
								>
									Approve
								</Button>
								<template v-else>
									<Button variant="ghost" @click="showCredentials(c)"
										>Credentials</Button
									>
									<Button variant="ghost" @click="setClient(c, 'Revoked')"
										>Revoke</Button
									>
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
		</div>

		<Dialog v-model="clientFormOpen" :options="{ title: 'New client' }">
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl
						v-model="clientForm.client_name"
						label="Name"
						placeholder="Partner A"
					/>
					<FormControl
						v-model="clientForm.description"
						type="textarea"
						label="Description"
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

		<Dialog
			v-model="clientAgentsOpen"
			:options="{ title: 'Which agents this client may call' }"
		>
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

		<Dialog v-model="credentialsOpen" :options="{ title: 'Client credentials' }">
			<template #body-content>
				<p class="text-sm text-gray-600 mb-3">
					Hand these to the caller out of band. The secret is shown because it is
					decrypted on request — it is never stored on the client record.
				</p>
				<div class="text-sm">
					<div class="mb-2">
						<span class="text-gray-500">API key</span>
						<code
							class="block bg-gray-100 rounded px-2 py-1 mt-0.5 break-all sm:break-normal"
							>{{ credentials.api_key }}</code
						>
					</div>
					<div>
						<span class="text-gray-500">API secret</span>
						<code
							class="block bg-gray-100 rounded px-2 py-1 mt-0.5 break-all sm:break-normal"
							>{{ credentials.api_secret }}</code
						>
					</div>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { Badge, Button, Dialog, ErrorMessage, FormControl, frappeRequest } from "frappe-ui";
import AgentPicker from "@/components/A2A/AgentPicker.vue";
import { A2A_API } from "@/utils/a2aApi";
import { statusTheme } from "@/utils/a2aFormat";

defineProps({
	ourAgents: { type: Array, default: () => [] },
});
const emit = defineEmits(["error", "count"]);

const clients = ref([]);
const loading = ref(false);
const saving = ref(false);
const formError = ref("");
const clientFormOpen = ref(false);
const clientAgentsOpen = ref(false);
const credentialsOpen = ref(false);
const clientForm = ref({ client_name: "", description: "", allowed_agents: [] });
const agentsForm = ref({ name: "", allowed_agents: [] });
const credentials = ref({ api_key: "", api_secret: "" });

watch(
	() => clients.value.length,
	(n) => emit("count", n),
);

async function loadClients() {
	loading.value = true;
	try {
		clients.value = (await frappeRequest({ url: A2A_API + "list_clients" })) || [];
	} catch (e) {
		emit("error", e.message || String(e));
	} finally {
		loading.value = false;
	}
}

function openClientForm() {
	formError.value = "";
	clientForm.value = { client_name: "", description: "", allowed_agents: [] };
	clientFormOpen.value = true;
}

async function saveClient() {
	formError.value = "";
	saving.value = true;
	try {
		await frappeRequest({
			url: A2A_API + "create_client",
			params: {
				client_name: clientForm.value.client_name,
				description: clientForm.value.description,
				allowed_agents: JSON.stringify(clientForm.value.allowed_agents),
			},
		});
		clientFormOpen.value = false;
		await loadClients();
	} catch (e) {
		formError.value = e.message || String(e);
	} finally {
		saving.value = false;
	}
}

function openClientAgents(client) {
	formError.value = "";
	agentsForm.value = { name: client.name, allowed_agents: [...(client.allowed_agents || [])] };
	clientAgentsOpen.value = true;
}

async function saveClientAgents() {
	formError.value = "";
	saving.value = true;
	try {
		await frappeRequest({
			url: A2A_API + "set_client_agents",
			params: {
				name: agentsForm.value.name,
				allowed_agents: JSON.stringify(agentsForm.value.allowed_agents),
			},
		});
		clientAgentsOpen.value = false;
		await loadClients();
	} catch (e) {
		formError.value = e.message || String(e);
	} finally {
		saving.value = false;
	}
}

async function setClient(client, status) {
	emit("error", "");
	try {
		await frappeRequest({
			url: A2A_API + "set_client_approval",
			params: { name: client.name, approval_status: status },
		});
		await loadClients();
	} catch (e) {
		emit("error", e.message || String(e));
	}
}

async function showCredentials(client) {
	emit("error", "");
	try {
		credentials.value = await frappeRequest({
			url: A2A_API + "get_client_credentials",
			params: { name: client.name },
		});
		credentialsOpen.value = true;
	} catch (e) {
		emit("error", e.message || String(e));
	}
}

onMounted(loadClients);
</script>
