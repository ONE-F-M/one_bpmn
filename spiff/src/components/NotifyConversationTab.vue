<template>
	<div class="space-y-5">
		<div>
			<span class="block text-xs font-medium text-gray-700 mb-2">Conversation actions</span>
			<div class="space-y-2">
				<div
					v-for="action in settings.actions"
					:key="action.key"
					class="border border-gray-200 rounded-lg px-3 py-2"
				>
					<div class="flex items-center gap-3">
						<span class="flex-1 text-sm text-gray-900">
							{{ CONVERSATION_ACTIONS[action.key].label }}
							<span class="text-gray-500"> · {{ CONVERSATION_ACTIONS[action.key].detail }}</span>
						</span>
						<label class="flex items-center gap-2 text-xs text-gray-600">
							<input
								type="checkbox"
								:checked="action.completes"
								@change="setCompletes(action.key, $event.target.checked)"
							/>
							Completes task
						</label>
						<button
							type="button"
							class="text-gray-400 hover:text-gray-700"
							:aria-label="`Remove ${CONVERSATION_ACTIONS[action.key].label}`"
							@click="removeAction(action.key)"
						>
							<Icon
								icon="lucide:x"
								class="w-4 h-4"
							/>
						</button>
					</div>
					<p
						v-if="action.completes"
						class="text-xs text-gray-400 mt-1"
					>
						The task ends when this is used. Conversation actions do not route the gateway or set a state.
					</p>
				</div>
			</div>
			<button
				v-if="missing"
				type="button"
				class="mt-2 text-sm text-blue-600 hover:text-blue-800"
				@click="addAction"
			>
				+ Add conversation action
			</button>
			<p class="text-xs text-gray-400 mt-2">
				Email only. Reply sends a Communication to the sender; Add Note adds a Comment. They do not route the gateway
				or set a state. Tick Completes task only if the task should end on that action.
			</p>
		</div>

		<div>
			<label class="flex items-center gap-2 text-sm font-medium text-gray-700">
				<input
					type="checkbox"
					:checked="settings.internalNotes"
					@change="update({ internalNotes: $event.target.checked })"
				/>
				Include internal notes
			</label>
			<p class="text-xs text-gray-400 mt-1">{{ notesHelp }}</p>
		</div>

		<div>
			<span class="block text-xs font-medium text-gray-700 mb-1">Saved Replies</span>
			<p
				v-if="!isTicket"
				class="text-xs text-gray-400"
			>
				Not offered: saved replies come from HD Saved Reply, a Helpdesk doctype, so they are shown for HD Ticket only.
			</p>
			<template v-else>
				<div class="flex flex-wrap gap-2 mb-2">
					<span
						v-for="name in settings.canned"
						:key="name"
						class="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-gray-100 text-xs text-gray-800"
					>
						{{ titleOf(name) }}
						<button
							type="button"
							class="text-gray-500 hover:text-gray-900"
							:aria-label="`Remove ${titleOf(name)}`"
							@click="update({ canned: settings.canned.filter((n) => n !== name) })"
						>
							<Icon
								icon="lucide:x"
								class="w-3 h-3"
							/>
						</button>
					</span>
				</div>
				<select
					aria-label="Add saved reply"
					class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
					:value="''"
					@change="addReply($event)"
				>
					<option value="">Add saved reply...</option>
					<option
						v-for="reply in available"
						:key="reply.name"
						:value="reply.name"
					>
						{{ reply.title }}: {{ reply.preview }}
					</option>
				</select>
				<p class="text-xs text-gray-400 mt-1">
					Picked from HD Saved Reply. Shown as one-tap replies when Reply is a conversation action.
				</p>
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed, watch } from "vue";
import { Icon } from "@iconify/vue";
import { CONVERSATION_ACTIONS, missingConversationAction, parseConversation } from "@/bpmn/shared/notifyConversation";
import { useSavedReplies } from "@/composables/useSavedReplies";

const props = defineProps({
	doctype: { type: String, default: "" },
});

// notifyConversation as a JSON string
const conversation = defineModel("conversation", { type: String });

const settings = computed(() => parseConversation(conversation.value));
const missing = computed(() => missingConversationAction(settings.value.actions));
const isTicket = computed(() => props.doctype === "HD Ticket");

const notesHelp = computed(() =>
	isTicket.value
		? "Adds HD Ticket Comment entries to the thread. Only agents receive this email."
		: `Adds Comments on the ${props.doctype} to the thread. Only the assignee receives this email.`
);

const { replies, load: loadReplies } = useSavedReplies();
watch(isTicket, (ticket) => ticket && loadReplies(), { immediate: true });

const available = computed(() =>
	replies.value
		.filter((r) => !settings.value.canned.includes(r.name))
		.map((r) => ({ name: r.name, title: r.title || r.name, preview: plainText(r.message).slice(0, 60) }))
);

// saved replies are stored by record name, which can differ from the title shown
function titleOf(name) {
	return replies.value.find((r) => r.name === name)?.title || name;
}

function plainText(html) {
	return new DOMParser().parseFromString(html || "", "text/html").body.textContent.trim();
}

function update(changes) {
	conversation.value = JSON.stringify({ ...settings.value, ...changes });
}

function setCompletes(key, completes) {
	update({ actions: settings.value.actions.map((a) => (a.key === key ? { ...a, completes } : a)) });
}

function removeAction(key) {
	update({ actions: settings.value.actions.filter((a) => a.key !== key) });
}

function addAction() {
	update({ actions: [...settings.value.actions, { key: missing.value, completes: false }] });
}

function addReply(event) {
	const name = event.target.value;
	event.target.value = "";
	if (name) update({ canned: [...settings.value.canned, name] });
}
</script>
