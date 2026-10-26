<template>
	<div class="space-y-4">
		<p class="text-xs text-gray-500">
			The actions, Confirm and Sign come from Task Actions in the panel. Primary and Reason only change the email; the
			task in ERPNext and the app is not affected.
		</p>

		<div>
			<label
				class="block text-xs font-medium text-gray-700 mb-1"
				:for="`${uid}-hours`"
			>Buttons work for</label>
			<div class="flex items-center gap-2">
				<input
					:id="`${uid}-hours`"
					v-model="hoursDraft"
					type="number"
					min="1"
					max="720"
					class="w-28 px-3 py-2 border border-gray-300 rounded-lg text-sm"
					@blur="commitHours"
				/>
				<span class="text-sm text-gray-700">hours</span>
			</div>
			<p class="text-xs text-gray-400 mt-1">
				Default 72. After this the email hides the buttons and shows Open in ERPNext. Allowed range 1 to 720 hours
				(30 days): after 30 days Gmail shows the HTML version anyway.
			</p>
		</div>

		<div v-if="conversationRows.length">
			<span class="block text-xs font-medium text-gray-700 mb-2">Finish the task from the conversation</span>
			<div class="space-y-2">
				<div
					v-for="conv in conversationRows"
					:key="conv.key"
					class="flex flex-wrap items-center gap-3"
				>
					<label
						class="w-48 text-sm text-gray-700"
						:for="`${uid}-finish-${conv.key}`"
					>{{ conv.label }}</label>
					<select
						:id="`${uid}-finish-${conv.key}`"
						class="flex-1 min-w-0 px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
						:value="conv.completesWith"
						@change="setFinish(conv.key, $event.target.value)"
					>
						<option value="">Don't finish</option>
						<option
							v-for="row in rows"
							:key="row.name"
							:value="row.name"
						>
							{{ row.name }}
						</option>
					</select>
				</div>
			</div>
			<p class="text-xs text-gray-400 mt-1">
				Conversation layout only. Picking a button means a reply or note also presses it, so the task ends and takes
				that button's path.
			</p>
		</div>

		<p
			v-if="!rows.length"
			class="text-sm text-gray-500"
		>
			This task has no Task Actions yet. Add them in the panel.
		</p>

		<div
			v-for="row in rows"
			:key="row.name"
			class="border border-gray-200 rounded-lg p-3 space-y-3"
		>
			<div class="flex items-center gap-2 text-sm font-medium text-gray-900">
				{{ row.name }}
				<span class="flex-1"></span>
				<span
					v-if="row.confirm"
					class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600"
				>Confirm</span>
				<span
					v-if="row.sign"
					class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600"
				>Sign</span>
			</div>

			<div class="flex flex-wrap gap-x-6 gap-y-2 text-sm text-gray-700">
				<label class="flex items-center gap-2">
					<input
						type="radio"
						:name="`${uid}-primary`"
						:checked="row.primary"
						@change="setPrimary(row.name)"
					/>
					Primary button
				</label>
				<label class="flex items-center gap-2">
					<input
						type="checkbox"
						:checked="row.reason"
						:disabled="row.sign"
						@change="update(row.name, { reason: $event.target.checked })"
					/>
					Ask for a reason
				</label>
			</div>
			<p
				v-if="row.sign"
				class="text-xs text-gray-400"
			>
				Sign opens ERPNext, so the email does not ask for a reason
			</p>

			<template v-if="row.reason">
				<div>
					<label
						class="block text-xs font-medium text-gray-700 mb-1"
						:for="`${uid}-${row.name}-field`"
					>Save reason to</label>
					<select
						:id="`${uid}-${row.name}-field`"
						:value="row.reasonField"
						class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
						@change="update(row.name, { reasonField: $event.target.value })"
					>
						<option value="">Select a field...</option>
						<option
							v-for="f in reasonFields"
							:key="f.fieldname"
							:value="f.fieldname"
						>
							{{ f.label }}
						</option>
					</select>
					<p
						v-if="!row.reasonField"
						class="text-xs text-amber-700 mt-1"
					>
						Pick a field. The email cannot save the reason without one.
					</p>
				</div>

				<div>
					<span class="block text-xs font-medium text-gray-700 mb-1">Reason chips</span>
					<div class="flex flex-wrap gap-2 mb-2">
						<span
							v-for="(chip, i) in row.chips"
							:key="`${chip[0]}-${i}`"
							class="inline-flex items-center gap-2 px-2 py-1 rounded-full bg-gray-100 text-xs text-gray-800"
						>
							{{ chip[0] }}
							<span dir="rtl">{{ chip[1] }}</span>
							<button
								type="button"
								class="text-gray-500 hover:text-gray-900"
								:aria-label="`Remove ${chip[0]}`"
								@click="removeChip(row, i)"
							>
								<Icon
									icon="lucide:x"
									class="w-3 h-3"
								/>
							</button>
						</span>
					</div>
					<div class="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
						<input
							v-model="drafts[row.name].en"
							type="text"
							placeholder="Add a chip in English"
							aria-label="Chip in English"
							class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
						/>
						<input
							v-model="drafts[row.name].ar"
							type="text"
							dir="rtl"
							placeholder="Arabic"
							aria-label="Chip in Arabic"
							class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
						/>
						<button
							type="button"
							class="px-3 py-2 rounded-lg text-sm bg-gray-900 text-white disabled:opacity-40"
							:disabled="!drafts[row.name].en.trim()"
							@click="addChip(row)"
						>
							Add
						</button>
					</div>
				</div>
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed, reactive, ref, useId, watch } from "vue";
import { Icon } from "@iconify/vue";
import { clampTokenHours, serializeTokenHours } from "@/bpmn/shared/notifyActions";
import { parseConversation } from "@/bpmn/shared/notifyConversation";
import { useDoctypeFields } from "@/composables/useDoctypeFields";

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

function removeChip(row, index) {
	update(row.name, { chips: row.chips.filter((_, i) => i !== index) });
}

const FINISH_LABELS = { reply: "When the agent replies", note: "When the agent adds a note" };

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
