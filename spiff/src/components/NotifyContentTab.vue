<template>
	<div class="space-y-4">
		<p
			v-if="htmlMode"
			class="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg p-3"
		>
			This task sends the Email Template or custom HTML from the last tab, as today. Layout, key facts and the
			Actions tab are not used. Turn it off there to pick a layout.
		</p>

		<div v-else>
			<label class="notify-label">Layout</label>
			<select
				v-model="layout"
				class="notify-input"
			>
				<option
					v-for="option in layoutOptions"
					:key="option.value"
					:value="option.value"
				>
					{{ option.label }}
				</option>
			</select>
			<p class="notify-help">{{ layoutHelp }}</p>
		</div>

		<div>
			<label class="notify-label">{{ htmlMode ? "Subject" : "Subject (English)" }}</label>
			<input
				v-model="subject"
				type="text"
				class="notify-input"
			/>
			<p
				class="notify-help"
				v-pre
			>
				Jinja template variables are supported: <code class="bg-gray-100 px-1 rounded">{{ doc.name }}</code>, etc.
			</p>
		</div>

		<template v-if="!htmlMode">
			<div>
				<label class="notify-label">Subject (Arabic)</label>
				<input
					v-model="subjectAr"
					type="text"
					dir="rtl"
					class="notify-input"
				/>
				<p class="notify-help">
					Sent as "English || Arabic", as today. Placeholders use doc.fieldname in double braces and are kept as they are.
				</p>
			</div>

			<div>
				<label class="notify-label">Context line</label>
				<div class="notify-input notify-readonly">{{ contextLine }}</div>
				<p class="notify-help">
					Read-only: DocType label and task name, shown above the question. The Arabic email uses the doctype's
					translation and the task name translated automatically.
				</p>
			</div>

			<div>
				<label class="notify-label">{{ isChat ? "Heading (English)" : "Question (English)" }}</label>
				<input
					v-model="questionEn"
					type="text"
					class="notify-input"
				/>
			</div>

			<div>
				<label class="notify-label">{{ isChat ? "Heading (Arabic)" : "Question (Arabic)" }}</label>
				<input
					v-model="questionAr"
					type="text"
					dir="rtl"
					class="notify-input"
				/>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue";

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

<style scoped>
.notify-label {
	display: block;
	margin-bottom: 0.25rem;
	font-size: 0.75rem;
	font-weight: 500;
	color: #374151;
}
.notify-input {
	width: 100%;
	padding: 0.5rem 0.75rem;
	border: 1px solid #d1d5db;
	border-radius: 0.5rem;
	font-size: 0.875rem;
	color: #111827;
	background: #ffffff;
}
.notify-input:focus {
	outline: none;
	border-color: #60a5fa;
	box-shadow: 0 0 0 2px #93c5fd;
}
.notify-readonly {
	background: #f9fafb;
	color: #4b5563;
}
.notify-help {
	margin-top: 0.25rem;
	font-size: 0.75rem;
	color: #9ca3af;
}
</style>
