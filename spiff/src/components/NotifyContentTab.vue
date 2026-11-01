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
			v-model="subject"
			type="text"
			:label="htmlMode ? 'Subject' : 'Subject (English)'"
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
			<FormControl
				v-model="subjectAr"
				type="text"
				dir="rtl"
				label="Subject (Arabic)"
				description="Sent as &quot;English || Arabic&quot;, as today. Placeholders use doc.fieldname in double braces and are kept as they are."
			/>

			<FormControl
				type="text"
				label="Context line"
				:model-value="contextLine"
				disabled
				description="Read-only: DocType label and task name, shown above the question. The Arabic email uses the doctype's translation and the task name translated automatically."
			/>

			<FormControl
				v-model="questionEn"
				type="text"
				:label="isChat ? 'Heading (English)' : 'Question (English)'"
			/>

			<FormControl
				v-model="questionAr"
				type="text"
				dir="rtl"
				:label="isChat ? 'Heading (Arabic)' : 'Question (Arabic)'"
			/>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue";
import { FormControl } from "frappe-ui";

const props = defineProps({
	htmlMode: { type: Boolean, required: true },
	doctype: { type: String, default: "" },
	taskName: { type: String, default: "" },
	emailThread: { type: Object, required: true },
});

const layout = defineModel("layout", { type: String });
const subject = defineModel("subject", { type: String });
const subjectAr = defineModel("subjectAr", { type: String });
const questionEn = defineModel("questionEn", { type: String });
const questionAr = defineModel("questionAr", { type: String });

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
