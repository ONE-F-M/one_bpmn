<template>
	<div class="space-y-5">
		<div class="space-y-2">
			<FormLabel label="Conversation actions" />
			<div
				v-for="action in settings.actions"
				:key="action.key"
				class="flex items-center gap-3 rounded-lg border border-outline-gray-2 px-3 py-2"
			>
				<span class="flex-1 text-base text-ink-gray-9">
					{{ CONVERSATION_ACTIONS[action.key].label }}
					<span class="text-ink-gray-5"> · {{ CONVERSATION_ACTIONS[action.key].detail }}</span>
				</span>
				<Button
					variant="ghost"
					icon="x"
					:aria-label="`Remove ${CONVERSATION_ACTIONS[action.key].label}`"
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
				Email only. Reply sends a Communication to the sender; Add Note adds a Comment. To also finish the task when
				one is used, pick a button under "Finish the task from the conversation" on the Actions tab.
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
				<div
					v-if="settings.canned.length"
					class="flex flex-wrap gap-1.5"
				>
					<Badge
						v-for="name in settings.canned"
						:key="name"
						size="lg"
						:label="titleOf(name)"
					>
						<template #suffix>
							<Button
								variant="ghost"
								size="sm"
								icon="x"
								class="!h-5 !w-5"
								:aria-label="`Remove ${titleOf(name)}`"
								@click="update({ canned: settings.canned.filter((n) => n !== name) })"
							/>
						</template>
					</Badge>
				</div>
				<Autocomplete
					:compare-fn="compareOption"
					:model-value="null"
					:options="available"
					placeholder="Add saved reply..."
					@update:model-value="addReply"
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
import { Autocomplete, Badge, Button, FormControl, FormLabel } from "frappe-ui";
import { compareOption } from "@/utils/compareOption";
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
	update({ actions: [...settings.value.actions, { key: missing.value, completesWith: "" }] });
}

function addReply(option) {
	if (option?.value) update({ canned: [...settings.value.canned, option.value] });
}
</script>
