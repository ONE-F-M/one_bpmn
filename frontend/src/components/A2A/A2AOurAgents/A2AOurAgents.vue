<template>
	<div class="flex-1 flex flex-col overflow-hidden">
		<div class="flex-1 overflow-auto px-4 sm:px-6 py-4">
			<p class="text-sm text-gray-600 mb-3">
				Every agent ticked <strong>Exposed over A2A</strong>, with the card the world would
				fetch. A card is public; this list is not — it stays behind admin access so nobody
				outside gets a directory of our agents.
			</p>
			<div v-if="loading" class="text-sm text-gray-500">Loading…</div>
			<div v-else class="overflow-x-auto rounded-lg">
				<table class="w-full min-w-[40rem] text-sm bg-white rounded-lg overflow-hidden">
					<thead class="bg-gray-100 text-left text-xs uppercase text-gray-500">
						<tr>
							<th class="px-4 py-2">Agent</th>
							<th class="px-4 py-2">Tags</th>
							<th class="px-4 py-2">Reachable by</th>
							<th class="px-4 py-2 text-right">Card</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="a in agents" :key="a.agent_id" class="border-t">
							<td class="px-4 py-2">
								<div class="font-medium text-gray-900">{{ a.agent_name }}</div>
								<div class="text-xs text-gray-500">
									{{ a.agent_id }} · {{ a.agent_type }}
								</div>
							</td>
							<td class="px-4 py-2">
								<span
									v-for="t in a.tags"
									:key="t"
									class="inline-block mr-1 mb-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-700"
								>
									{{ t }}
								</span>
								<span v-if="!a.tags.length" class="text-gray-400 text-xs"
									>no tags</span
								>
							</td>
							<td class="px-4 py-2 text-gray-600">
								<span v-if="a.reachable_by.length">{{
									a.reachable_by.join(", ")
								}}</span>
								<span
									v-else
									class="text-gray-400"
									title="Its card is public, but no approved client lists it"
								>
									nobody outside
								</span>
							</td>
							<td class="px-4 py-2 text-right whitespace-nowrap">
								<Button variant="ghost" @click="copyCardUrl(a)">
									{{ copied === a.agent_id ? "Copied" : "Copy link" }}
								</Button>
								<Button variant="ghost" @click="showCard(a)">View</Button>
							</td>
						</tr>
						<tr v-if="!agents.length">
							<td colspan="4" class="px-4 py-6 text-center text-gray-500">
								No agents are exposed yet. Tick “Exposed over A2A” on an enabled,
								Live agent.
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<Dialog v-model="cardOpen" :options="{ title: 'Agent card', size: '2xl' }">
			<template #body-content>
				<div v-if="openCard">
					<p class="text-sm text-gray-600 mb-2">
						This is exactly what an unauthenticated fetch of the card URL returns. It
						is generated from the configuration each time, so it cannot fall out of
						date.
					</p>
					<div class="text-xs text-gray-500 mb-3 break-all">
						<div class="mb-1">
							<span class="text-gray-400">Card:</span> {{ openCard.card_url }}
						</div>
						<div><span class="text-gray-400">Tasks:</span> {{ openCard.rpc_url }}</div>
					</div>
					<pre class="bg-gray-100 rounded p-3 text-xs overflow-auto max-h-96">{{
						JSON.stringify(openCard.card, null, 2)
					}}</pre>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { onMounted, ref, watch } from "vue";
import { Button, Dialog, frappeRequest } from "frappe-ui";
import { A2A_API } from "@/utils/a2aApi";

const agents = defineModel("agents", { type: Array, default: () => [] });
const emit = defineEmits(["error", "count"]);

const loading = ref(false);
const cardOpen = ref(false);
const openCard = ref(null);
const copied = ref("");

watch(
	() => agents.value.length,
	(n) => emit("count", n),
);

async function loadAgents() {
	loading.value = true;
	try {
		agents.value = (await frappeRequest({ url: A2A_API + "list_agent_cards" })) || [];
	} catch (e) {
		emit("error", e.message || String(e));
	} finally {
		loading.value = false;
	}
}

function showCard(agent) {
	openCard.value = agent;
	cardOpen.value = true;
}

async function copyCardUrl(agent) {
	try {
		await navigator.clipboard.writeText(agent.card_url);
		copied.value = agent.agent_id;
		setTimeout(() => (copied.value = ""), 1500);
	} catch {
		emit("error", "Could not copy the link — select it from the card view instead.");
	}
}

onMounted(loadAgents);
</script>
