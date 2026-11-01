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
			description="Default 72. After this the email hides the buttons and shows Open in ERPNext. Allowed range 1 to 720 hours (30 days): after 30 days Gmail shows the HTML version anyway."
			@blur="commitHours"
		/>

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
					<FormLabel label="Reason chips · Arabic is translated automatically" />
					<NotifyTagBox
						:tags="chipTags(row)"
						@remove="(i) => removeChip(row, i)"
					/>
					<div class="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
						<TextInput
							:model-value="drafts[row.name].en"
							placeholder="Add a chip in English"
							aria-label="Chip in English"
							@update:model-value="(value) => setChipEnglish(row.name, value)"
						/>
						<TextInput
							:model-value="drafts[row.name].ar"
							dir="rtl"
							placeholder="Arabic"
							aria-label="Chip in Arabic"
							@update:model-value="(value) => setChipArabic(row.name, value)"
						/>
						<Button
							variant="outline"
							label="Add"
							:loading="adding === row.name"
							:disabled="!drafts[row.name].en.trim()"
							@click="addChip(row)"
						/>
					</div>
					<ErrorMessage
						v-if="chipErrors[chipKey(row.name)]"
						:message="chipErrors[chipKey(row.name)]"
					/>
				</div>
			</template>
		</div>
	</div>
</template>

<script setup>
import { computed, reactive, ref, toRef, useId, watch } from "vue";
import { Badge, Button, ErrorMessage, FormControl, FormLabel, TextInput } from "frappe-ui";
import { clampTokenHours, serializeTokenHours } from "@/bpmn/shared/notifyActions";
import { useArabicTranslation } from "@/composables/useArabicTranslation";
import { useDoctypeFields } from "@/composables/useDoctypeFields";
import NotifyTagBox from "@/components/NotifyTagBox.vue";

const props = defineProps({
	taskActions: { type: Array, required: true },
	doctype: { type: String, default: "" },
	processModel: { type: String, default: "" },
});

// settings keyed by action name, already merged with the current Task Actions
const actions = defineModel("actions", { type: Object, required: true });
const hours = defineModel("hours", { type: String });

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

// chip drafts the author typed Arabic into, so translation leaves them alone
const chipEdited = ref([]);
const { queue, translateAgain, markEdited, isEdited, errors: chipErrors } = useArabicTranslation({
	edited: chipEdited,
	processModel: toRef(props, "processModel"),
});
const adding = ref("");

// each draft gets its own key, so a late translation never fills the next draft
const draftCount = reactive({});
const chipKey = (name) => `chip:${name}:${draftCount[name] || 0}`;

function fillChipArabic(name, key) {
	return (text) => {
		if (chipKey(name) === key) drafts[name].ar = text;
	};
}

function setChipEnglish(name, value) {
	drafts[name].en = value;
	const key = chipKey(name);
	queue(key, value, fillChipArabic(name, key));
}

function setChipArabic(name, value) {
	drafts[name].ar = value;
	markEdited(chipKey(name));
}

// A chip whose Arabic is still empty is translated before it is added; on failure the draft stays to fill by hand
async function addChip(row) {
	const key = chipKey(row.name);
	const draft = drafts[row.name];
	if (!draft.ar.trim() && !isEdited(key)) {
		adding.value = row.name;
		try {
			await translateAgain(key, draft.en.trim(), fillChipArabic(row.name, key));
		} finally {
			adding.value = "";
		}
		if (chipErrors.value[key]) return;
	}
	update(row.name, { chips: [...row.chips, [draft.en.trim(), draft.ar.trim()]] });
	drafts[row.name] = { en: "", ar: "" };
	draftCount[row.name] = (draftCount[row.name] || 0) + 1;
}

function chipTags(row) {
	return row.chips.map(([en, ar], i) => ({ key: i, label: en, sub: ar }));
}

function removeChip(row, index) {
	update(row.name, { chips: row.chips.filter((_, i) => i !== index) });
}

const hoursDraft = ref(String(clampTokenHours(hours.value)));
watch(hours, (v) => (hoursDraft.value = String(clampTokenHours(v))));

function commitHours() {
	const clamped = clampTokenHours(hoursDraft.value);
	hoursDraft.value = String(clamped);
	hours.value = serializeTokenHours(clamped);
}
</script>
