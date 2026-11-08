<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<div
				class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4 mb-3"
			>
				<p class="text-sm text-gray-600">
					Our processes may delegate only to an entry that is enabled and approved. Fetch
					the card first — the card is what you are approving. Changing an endpoint sends
					the entry back to Draft.
				</p>
				<Button variant="solid" @click="openRemoteForm()">New remote agent</Button>
			</div>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[44rem] text-sm bg-white rounded-lg overflow-hidden">
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
								<span v-if="!r.enabled" class="ml-1 text-xs text-gray-400"
									>(disabled)</span
								>
							</td>
							<td class="px-4 py-2 text-gray-600 truncate max-w-xs">
								{{ r.endpoint_url }}
							</td>
							<td class="px-4 py-2 text-gray-600">
								<span v-if="r.card_name">{{ r.card_name }}</span>
								<span v-else class="text-gray-400">not fetched</span>
							</td>
							<td class="px-4 py-2">
								<Badge :theme="statusTheme(r.approval_status)">{{
									r.approval_status
								}}</Badge>
							</td>
							<td class="px-4 py-2 text-right whitespace-nowrap">
								<Button variant="ghost" @click="openRemoteForm(r)">Edit</Button>
								<Button variant="ghost" @click="fetchCard(r)">Fetch card</Button>
								<Button
									v-if="r.approval_status !== 'Approved'"
									variant="ghost"
									:disabled="!r.card_name"
									@click="setRemote(r, 'Approved')"
								>
									Approve
								</Button>
								<Button v-else variant="ghost" @click="setRemote(r, 'Revoked')"
									>Revoke</Button
								>
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
		</div>

		<Dialog
			v-model="remoteFormOpen"
			:options="{ title: remoteForm.name ? 'Edit remote agent' : 'New remote agent' }"
		>
			<template #body-content>
				<div class="flex flex-col gap-3">
					<FormControl
						v-model="remoteForm.agent_name"
						label="Name"
						:disabled="!!remoteForm.name"
						placeholder="Partner Support Agent"
					/>
					<FormControl
						v-model="remoteForm.endpoint_url"
						label="Endpoint URL"
						placeholder="https://partner.example.com/a2a"
						description="Where its A2A endpoint lives. Changing this later sends the entry back to Draft."
					/>
					<FormControl
						v-model="remoteForm.auth_scheme"
						type="select"
						label="Auth scheme"
						:options="authSchemes"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme === 'API Key Header'"
						v-model="remoteForm.auth_header_name"
						label="Auth header name"
						placeholder="Authorization"
					/>
					<FormControl
						v-if="remoteForm.auth_scheme !== 'None'"
						v-model="remoteForm.credential"
						type="password"
						label="Credential"
						description="Stored encrypted and read only when a call is made."
					/>
					<div class="grid grid-cols-2 gap-3">
						<FormControl
							v-model="remoteForm.request_timeout"
							label="Request timeout (s)"
							placeholder="30"
						/>
						<FormControl
							v-model="remoteForm.default_task_timeout_minutes"
							label="Task deadline (min)"
							placeholder="240"
						/>
						<FormControl
							v-model="remoteForm.poll_base_interval"
							label="Poll base (s)"
							placeholder="60"
						/>
						<FormControl
							v-model="remoteForm.poll_max_interval"
							label="Poll max (s)"
							placeholder="900"
						/>
					</div>
					<FormControl
						v-model="remoteForm.allow_internal_hosts"
						type="checkbox"
						label="Allow internal hosts"
						description="Only for pointing at this site itself. Leave off for real partners."
					/>
					<ErrorMessage v-if="formError" :message="formError" />
					<p class="text-xs text-gray-500">
						Saved as Draft. Fetch its card and approve it before any process can use
						it.
					</p>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" :loading="saving" @click="saveRemote">
					{{ remoteForm.name ? "Save" : "Create" }}
				</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { Badge, Button, Dialog, ErrorMessage, FormControl, frappeRequest } from "frappe-ui";
import { A2A_API } from "@/utils/a2aApi";
import { statusTheme } from "@/utils/a2aFormat";

const emit = defineEmits(["error", "count"]);

const authSchemes = [
	{ label: "None", value: "None" },
	{ label: "Bearer", value: "Bearer" },
	{ label: "API Key Header", value: "API Key Header" },
];

const remotes = ref([]);
const loading = ref(false);
const saving = ref(false);
const formError = ref("");
const remoteFormOpen = ref(false);
const remoteForm = ref(blankRemote());

watch(
	() => remotes.value.length,
	(n) => emit("count", n),
);

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
	};
}

async function loadRemotes() {
	loading.value = true;
	try {
		remotes.value = (await frappeRequest({ url: A2A_API + "list_remote_agents" })) || [];
	} catch (e) {
		emit("error", e.message || String(e));
	} finally {
		loading.value = false;
	}
}

function openRemoteForm(remote) {
	formError.value = "";
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
		: blankRemote();
	remoteFormOpen.value = true;
}

async function saveRemote() {
	formError.value = "";
	saving.value = true;
	const f = remoteForm.value;
	const payload = {
		endpoint_url: f.endpoint_url,
		auth_scheme: f.auth_scheme,
		auth_header_name: f.auth_header_name,
		allow_internal_hosts: f.allow_internal_hosts ? 1 : 0,
		request_timeout: f.request_timeout || undefined,
		default_task_timeout_minutes: f.default_task_timeout_minutes || undefined,
		poll_base_interval: f.poll_base_interval || undefined,
		poll_max_interval: f.poll_max_interval || undefined,
	};
	// An empty credential on edit leaves the stored one alone.
	if (f.credential) payload.credential = f.credential;
	try {
		if (f.name) {
			await frappeRequest({
				url: A2A_API + "update_remote_agent",
				params: { name: f.name, ...payload },
			});
		} else {
			await frappeRequest({
				url: A2A_API + "create_remote_agent",
				params: { agent_name: f.agent_name, ...payload },
			});
		}
		remoteFormOpen.value = false;
		await loadRemotes();
	} catch (e) {
		formError.value = e.message || String(e);
	} finally {
		saving.value = false;
	}
}

async function fetchCard(remote) {
	emit("error", "");
	try {
		await frappeRequest({ url: A2A_API + "fetch_remote_card", params: { name: remote.name } });
		await loadRemotes();
	} catch (e) {
		emit("error", e.message || String(e));
	}
}

async function setRemote(remote, status) {
	emit("error", "");
	try {
		await frappeRequest({
			url: A2A_API + "set_remote_approval",
			params: { name: remote.name, approval_status: status },
		});
		await loadRemotes();
	} catch (e) {
		emit("error", e.message || String(e));
	}
}

onMounted(loadRemotes);
</script>
