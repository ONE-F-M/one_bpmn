<template>
	<div class="space-y-4">
		<p class="text-p-sm text-ink-gray-5">
			The actions, Confirm and Sign come from Task Actions in the panel. Primary and Reason only change the email; the
			task in ERPNext and the app is not affected.
		</p>

		<FormControl
			v-model="hoursDraft"
			type="number"
			label="Buttons work for (hours)"
			min="1"
			max="720"
			class="[&_input]:max-w-[12rem]"
			description="Default 72. After this the email hides the buttons and shows Open in ERPNext. Allowed range 1 to 720 hours (30 days): after 30 days Gmail shows the HTML version anyway."
			@blur="commitHours"
		/>

		<div
			v-if="conversationRows.length"
			class="space-y-2"
		>
			<FormLabel label="Finish the task from the conversation" />
			<FormControl
				v-for="conv in conversationRows"
				:key="conv.key"
				type="select"
				:label="conv.label"
				:model-value="conv.completesWith"
				:options="finishOptions"
				@update:model-value="(value) => setFinish(conv.key, value)"
			/>
			<p class="text-p-sm text-ink-gray-5">
				Conversation layout only. Picking a button means a reply or note also presses it, so the task ends and takes
				that button's path.
			</p>
		</div>

		<p
			v-if="!rows.length"
			class="text-p-base text-ink-gray-5"
		>
			This task has no Task Actions yet. Add them in the panel.
		</p>

		<div
			v-for="row in rows"
			:key="row.name"
			class="space-y-3 rounded-lg border border-outline-gray-2 p-3"
		>
			<div class="flex items-center gap-2 text-base font-medium text-ink-gray-9">
				{{ row.name }}
				<span class="flex-1"></span>
				<Badge
					v-if="row.confirm"
					label="Confirm"
				/>
				<Badge
					v-if="row.sign"
					label="Sign"
				/>
			</div>

			<div class="flex flex-wrap items-center gap-x-6 gap-y-2">
				<label class="flex items-center gap-2 text-base text-ink-gray-7">
					<input
						type="radio"
						class="text-ink-gray-9 focus:ring-outline-gray-3"
						:name="`${uid}-primary`"
						:checked="row.primary"
						@change="setPrimary(row.name)"
					/>
					Primary button
				</label>
				<FormControl
					type="checkbox"
					label="Ask for a reason"
					:model-value="row.reason"
					:disabled="row.sign"
					@update:model-value="(on) => update(row.name, { reason: on })"
				/>
			</div>
			<p
				v-if="row.sign"
				class="text-p-sm text-ink-gray-5"
			>
				Sign opens ERPNext, so the email does not ask for a reason
			</p>

			<template v-if="row.reason">
				<FormControl
					type="select"
					label="Save reason to"
					placeholder="Select a field..."
					:model-value="row.reasonField"
					:options="reasonFieldOptions"
					@update:model-value="(value) => update(row.name, { reasonField: value })"
				>
					<template #description>
						<ErrorMessage
							v-if="!row.reasonField"
							message="Pick a field. The email cannot save the reason without one."
						/>
					</template>
				</FormControl>

				<div class="space-y-1.5">
					<FormLabel label="Reason chips" />
					<NotifyTagBox
						:tags="chipTags(row)"
						@remove="(i) => removeChip(row, i)"
					/>
					<div class="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
						<TextInput
							v-model="drafts[row.name].en"
							placeholder="Add a chip in English"
							aria-label="Chip in English"
						/>
						<TextInput
							v-model="drafts[row.name].ar"
							dir="rtl"
							placeholder="Arabic"
							aria-label="Chip in Arabic"
						/>
						<Button
							variant="outline"
							label="Add"
							:disabled="!drafts[row.name].en.trim()"
							@click="addChip(row)"
						/>
					</div>
				</div>
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed, reactive, ref, useId, watch } from "vue";
import { Badge, Button, ErrorMessage, FormControl, FormLabel, TextInput } from "frappe-ui";
import { clampTokenHours, serializeTokenHours } from "@/bpmn/shared/notifyActions";
import { parseConversation } from "@/bpmn/shared/notifyConversation";
import { useDoctypeFields } from "@/composables/useDoctypeFields";
import NotifyTagBox from "@/components/NotifyTagBox.vue";

const props = defineProps({
	taskActions: { type: Array, required: true },
	doctype: { type: String, default: "" },
	layout: { type: String, default: "" },
});

// settings keyed by action name, already merged with the current Task Actions
const actions = defineModel("actions", { type: Object, required: true });
const hours = defineModel("hours", { type: String });
// notifyConversation as a JSON string; the finish settings are shown here for the Conversation layout
const conversation = defineModel("conversation", { type: String });

const uid = useId();
const { fields: reasonFields, load: loadReasonFields } = useDoctypeFields(["Text", "Small Text", "Text Editor", "Data"]);
watch(() => props.doctype, loadReasonFields, { immediate: true });

const reasonFieldOptions = computed(() => reasonFields.value.map((f) => ({ label: f.label, value: f.fieldname })));

const flags = computed(() => Object.fromEntries(props.taskActions.map((a) => [a.action, a])));

const rows = computed(() =>
	Object.entries(actions.value).map(([name, settings]) => ({
		name,
		...settings,
		confirm: flags.value[name]?.confirmTransition === "true",
		sign: flags.value[name]?.requireDigitalSignature === "true",
	}))
);

function update(name, changes) {
	actions.value = { ...actions.value, [name]: { ...actions.value[name], ...changes } };
}

function setPrimary(name) {
	actions.value = Object.fromEntries(
		Object.entries(actions.value).map(([n, s]) => [n, { ...s, primary: n === name }])
	);
}

// chip text being typed, per action
const drafts = reactive({});
watch(rows, (list) => {
	for (const row of list) drafts[row.name] ??= { en: "", ar: "" };
}, { immediate: true });

function addChip(row) {
	const draft = drafts[row.name];
	update(row.name, { chips: [...row.chips, [draft.en.trim(), draft.ar.trim()]] });
	drafts[row.name] = { en: "", ar: "" };
}

function chipTags(row) {
	return row.chips.map(([en, ar], i) => ({ key: i, label: en, sub: ar }));
}

function removeChip(row, index) {
	update(row.name, { chips: row.chips.filter((_, i) => i !== index) });
}

const FINISH_LABELS = { reply: "When the agent replies", note: "When the agent adds a note" };

const finishOptions = computed(() => [
	{ label: "Don't finish", value: "" },
	...rows.value.map((row) => ({ label: row.name, value: row.name })),
]);

const conversationRows = computed(() =>
	props.layout === "chat"
		? parseConversation(conversation.value).actions.map((a) => ({ ...a, label: FINISH_LABELS[a.key] }))
		: []
);

function setFinish(key, completesWith) {
	const settings = parseConversation(conversation.value);
	conversation.value = JSON.stringify({
		...settings,
		actions: settings.actions.map((a) => (a.key === key ? { ...a, completesWith } : a)),
	});
}

const hoursDraft = ref(String(clampTokenHours(hours.value)));
watch(hours, (v) => (hoursDraft.value = String(clampTokenHours(v))));

function commitHours() {
	const clamped = clampTokenHours(hoursDraft.value);
	hoursDraft.value = String(clamped);
	hours.value = serializeTokenHours(clamped);
}
</script>
