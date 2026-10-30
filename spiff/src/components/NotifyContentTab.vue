<template>
	<div class="space-y-4">
		<p
			v-if="htmlMode"
			class="rounded bg-surface-gray-2 p-3 text-p-sm text-ink-gray-7"
		>
			This task sends the Email Template or custom HTML from the last tab, as today. Layout, key facts and the
			Actions tab are not used. Turn it off there to pick a layout.
		</p>

		<FormControl
			v-else
			v-model="layout"
			type="select"
			label="Layout"
			:options="layoutOptions"
			:description="layoutHelp"
		/>

		<FormControl
			type="text"
			:label="htmlMode ? 'Subject' : 'Subject (English)'"
			:model-value="subject"
			@update:model-value="(value) => setEnglish('notifySubjectAr', value)"
		>
			<template #description>
				<p
					class="text-p-sm text-ink-gray-5"
					v-pre
				>
					Jinja template variables are supported: <code>{{ doc.name }}</code>, etc.
				</p>
			</template>
		</FormControl>

		<template v-if="!htmlMode">
			<NotifyArabicInput
				label="Subject (Arabic)"
				:model-value="subjectAr"
				:edited="isEdited('notifySubjectAr')"
				:error="errors.notifySubjectAr"
				hint="Sent as &quot;English || Arabic&quot;, as today. Placeholders use doc.fieldname in double braces and are kept as they are."
				@update:model-value="(value) => setArabic('notifySubjectAr', value)"
				@translate-again="again('notifySubjectAr')"
			/>

			<FormControl
				type="text"
				label="Context line"
				:model-value="contextLine"
				disabled
				description="Read-only: DocType label and task name, shown above the question. The Arabic email uses the doctype's translation and the task name translated automatically."
			/>

			<FormControl
				type="text"
				:label="isChat ? 'Heading (English)' : 'Question (English)'"
				:model-value="questionEn"
				@update:model-value="(value) => setEnglish('notifyQuestionAr', value)"
			/>

			<NotifyArabicInput
				:label="isChat ? 'Heading (Arabic)' : 'Question (Arabic)'"
				:model-value="questionAr"
				:edited="isEdited('notifyQuestionAr')"
				:error="errors.notifyQuestionAr"
				@update:model-value="(value) => setArabic('notifyQuestionAr', value)"
				@translate-again="again('notifyQuestionAr')"
			/>
		</template>
	</div>
</template>

<script setup>
import { computed, toRef } from "vue";
import { FormControl } from "frappe-ui";
import NotifyArabicInput from "@/components/NotifyArabicInput.vue";
import { parseFieldList, serializeFieldList } from "@/bpmn/shared/notifyFields";
import { useArabicTranslation } from "@/composables/useArabicTranslation";

const props = defineProps({
	htmlMode: { type: Boolean, required: true },
	doctype: { type: String, default: "" },
	taskName: { type: String, default: "" },
	emailThread: { type: Object, required: true },
	processModel: { type: String, default: "" },
});

const layout = defineModel("layout", { type: String });
const subject = defineModel("subject", { type: String });
const subjectAr = defineModel("subjectAr", { type: String });
const questionEn = defineModel("questionEn", { type: String });
const questionAr = defineModel("questionAr", { type: String });
// JSON list of the Arabic fields the author edited by hand
const arabicEdited = defineModel("arabicEdited", { type: String });

const edited = computed({
	get: () => parseFieldList(arabicEdited.value),
	set: (list) => (arabicEdited.value = serializeFieldList(list)),
});
const { queue, translateAgain, markEdited, isEdited, errors } = useArabicTranslation({
	edited,
	processModel: toRef(props, "processModel"),
});

// each Arabic attribute and the English it is translated from
const pairs = { notifySubjectAr: [subject, subjectAr], notifyQuestionAr: [questionEn, questionAr] };

function setEnglish(field, value) {
	const [english, arabic] = pairs[field];
	english.value = value;
	if (!props.htmlMode) queue(field, value, (text) => (arabic.value = text));
}

function setArabic(field, value) {
	pairs[field][1].value = value;
	markEdited(field);
}

function again(field) {
	const [english, arabic] = pairs[field];
	translateAgain(field, english.value, (text) => (arabic.value = text));
}

const isChat = computed(() => layout.value === "chat");

const layoutOptions = computed(() => [
	...(props.emailThread.email_append_to ? [{ value: "chat", label: "Conversation" }] : []),
	{ value: "card", label: "Decision card" },
	{ value: "steps", label: "Step by step" },
]);

const layoutHelp = computed(() => {
	if (!props.doctype) return "Conversation is not listed: this process has no DocType.";
	return props.emailThread.email_append_to
		? `Conversation is listed because ${props.doctype} has email_append_to = 1: emails from ${props.emailThread.sender_field} are added to the document as Communications.`
		: `Conversation is not listed: ${props.doctype} has email_append_to = 0, so there is no email thread to show.`;
});

const contextLine = computed(() => [props.doctype, props.taskName].filter(Boolean).join(" · "));
</script>
