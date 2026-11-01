<template>
	<div class="space-y-4">
		<div class="space-y-2">
			<FormLabel label="Conversation actions" />
			<div
				v-for="action in settings.actions"
				:key="action.key"
				class="flex items-start gap-3 rounded-lg border border-outline-gray-2 p-3"
			>
				<FormControl
					class="flex-1"
					type="text"
					:label="CONVERSATION_ACTIONS[action.key].label"
					:placeholder="CONVERSATION_ACTIONS[action.key].label"
					:description="`${CONVERSATION_ACTIONS[action.key].detail}. The text is the button label in the email.`"
					:model-value="action.label"
					@change="(event) => setLabel(action.key, event.target.value)"
				/>
				<Button
					class="mt-5"
					variant="ghost"
					icon="x"
					:label="`Remove ${action.label}`"
					@click="removeAction(action.key)"
				/>
			</div>
			<Button
				v-if="missing"
				variant="subtle"
				icon-left="plus"
				label="Add conversation action"
				@click="addAction"
			/>
			<p class="text-p-sm text-ink-gray-5">
				Email only. The reply goes to the sender as a Communication; the note is added as a Comment. Neither finishes
				the task: the task's own action buttons do that.
			</p>
		</div>

		<div class="space-y-1.5">
			<FormControl
				type="checkbox"
				label="Include internal notes"
				:model-value="settings.internalNotes"
				@update:model-value="(on) => update({ internalNotes: on })"
			/>
			<p class="text-p-sm text-ink-gray-5">{{ notesHelp }}</p>
		</div>

		<div class="space-y-1.5">
			<FormLabel label="Saved Replies" />
			<p
				v-if="!isTicket"
				class="text-p-sm text-ink-gray-5"
			>
				Not offered: saved replies come from HD Saved Reply, a Helpdesk doctype, so they are shown for HD Ticket only.
			</p>
			<template v-else>
				<NotifyTagBox
					:tags="cannedTags"
					:options="available"
					placeholder="Add saved reply..."
					@add="addReply"
					@remove="(name) => update({ canned: settings.canned.filter((n) => n !== name) })"
				/>
				<p class="text-p-sm text-ink-gray-5">
					Picked from HD Saved Reply. Shown as one-tap replies when Reply is a conversation action.
				</p>
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed, watch } from "vue";
import { Button, FormControl, FormLabel } from "frappe-ui";
import NotifyTagBox from "@/components/NotifyTagBox.vue";
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
		.map((r) => ({ label: r.title || r.name, value: r.name, description: plainText(r.message).slice(0, 60) }))
);

const cannedTags = computed(() => settings.value.canned.map((name) => ({ key: name, label: titleOf(name) })));

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

function removeAction(key) {
	update({ actions: settings.value.actions.filter((a) => a.key !== key) });
}

function addAction() {
	update({ actions: [...settings.value.actions, { key: missing.value, label: CONVERSATION_ACTIONS[missing.value].label }] });
}

function setLabel(key, label) {
	update({ actions: settings.value.actions.map((a) => (a.key === key ? { ...a, label: label.trim() } : a)) });
}

function addReply(option) {
	if (option?.value) update({ canned: [...settings.value.canned, option.value] });
}
</script>
