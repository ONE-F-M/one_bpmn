<template>
	<div class="space-y-4">
		<p
			v-if="useHtml"
			class="rounded border border-dashed border-outline-blue-1 bg-surface-blue-1 p-3 text-p-sm text-ink-blue-3"
		>
			This task sends the custom HTML from the last tab, as today. Heading, message and key facts are not used. Turn it
			off there to send the Notice.
		</p>

		<FormControl
			type="text"
			:label="useHtml ? 'Subject · required' : 'Subject (English) · required'"
			placeholder="e.g. Action Required: {{ doc.name }}"
			:model-value="values.emailSubject"
			@update:model-value="(value) => setEnglish('emailSubject', value)"
		>
			<template #description>
				<ErrorMessage
					v-if="subjectError"
					:message="subjectError"
				/>
				<p
					v-else
					v-pre
					class="text-p-sm text-ink-gray-5"
				>
					Supports Jinja2: use {{ doc.field_name }} for document values.
				</p>
			</template>
		</FormControl>

		<template v-if="!useHtml">
			<NotifyArabicInput
				label="Subject (Arabic, auto-translated)"
				:model-value="values.emailSubjectAr"
				:edited="isEdited('emailSubjectAr')"
				:error="errors.emailSubjectAr"
				hint="Sent as &quot;English || Arabic&quot;."
				@update:model-value="(value) => setArabic('emailSubjectAr', value)"
				@translate-again="again('emailSubjectAr')"
			/>

			<FormControl
				type="text"
				label="Context line"
				:model-value="`${doctype || 'Document'} · Notice`"
				disabled
				description="Read-only: the DocType label, shown above the heading."
			/>

			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<FormControl
					type="text"
					label="Heading (English)"
					:model-value="values.emailHeadingEn"
					@update:model-value="(value) => setEnglish('emailHeadingEn', value)"
				/>
				<NotifyArabicInput
					label="Heading (Arabic)"
					:model-value="values.emailHeadingAr"
					:edited="isEdited('emailHeadingAr')"
					:error="errors.emailHeadingAr"
					@update:model-value="(value) => setArabic('emailHeadingAr', value)"
					@translate-again="again('emailHeadingAr')"
				/>
				<FormControl
					type="textarea"
					label="Message (English)"
					:rows="4"
					:model-value="values.emailMessageEn"
					@update:model-value="(value) => setEnglish('emailMessageEn', value)"
				/>
				<NotifyArabicInput
					type="textarea"
					label="Message (Arabic)"
					:model-value="values.emailMessageAr"
					:edited="isEdited('emailMessageAr')"
					:error="errors.emailMessageAr"
					@update:model-value="(value) => setArabic('emailMessageAr', value)"
					@translate-again="again('emailMessageAr')"
				/>
			</div>

			<FormControl
				v-if="useDoctype"
				type="checkbox"
				label="Show live status"
				description="Shows the document's Workflow State, coloured by its style, when the email is opened."
				:model-value="values.emailShowStatus === 'true'"
				@update:model-value="(on) => emit('update', 'emailShowStatus', on ? 'true' : '')"
			/>
		</template>
	</div>
</template>

<script setup>
import { computed, toRef } from "vue";
import { ErrorMessage, FormControl } from "frappe-ui";
import NotifyArabicInput from "@/components/NotifyArabicInput.vue";
import { parseFieldList, serializeFieldList } from "@/bpmn/shared/notifyFields";
import { useArabicTranslation } from "@/composables/useArabicTranslation";

const props = defineProps({
	// the dialog's working copy of the email attributes
	values: { type: Object, required: true },
	doctype: { type: String, default: "" },
	useHtml: { type: Boolean, default: false },
	useDoctype: { type: Boolean, default: false },
	processModel: { type: String, default: "" },
	subjectError: { type: String, default: "" },
});

const emit = defineEmits(["update"]);

// emailArabicEdited lists the Arabic fields the author typed by hand
const edited = computed({
	get: () => parseFieldList(props.values.emailArabicEdited),
	set: (list) => emit("update", "emailArabicEdited", serializeFieldList(list)),
});
const { queue, translateAgain, markEdited, isEdited, errors } = useArabicTranslation({
	edited,
	processModel: toRef(props, "processModel"),
});

// each English field and the Arabic field filled from it
const ARABIC_OF = { emailSubject: "emailSubjectAr", emailHeadingEn: "emailHeadingAr", emailMessageEn: "emailMessageAr" };
const ENGLISH_OF = Object.fromEntries(Object.entries(ARABIC_OF).map(([en, ar]) => [ar, en]));

function setEnglish(name, value) {
	emit("update", name, value);
	if (props.useHtml) return;
	const arabic = ARABIC_OF[name];
	queue(arabic, value, (text) => emit("update", arabic, text));
}

function setArabic(name, value) {
	emit("update", name, value);
	markEdited(name);
}

function again(name) {
	translateAgain(name, props.values[ENGLISH_OF[name]], (text) => emit("update", name, text));
}
</script>
