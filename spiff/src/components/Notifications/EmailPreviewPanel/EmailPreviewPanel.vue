<template>
	<div class="flex min-w-0 flex-col gap-2">
		<div class="flex items-center justify-between gap-2">
			<p class="text-sm font-medium text-ink-gray-8">
				{{ preview.docname ? `Live preview · ${preview.docname}` : "Live preview" }}
			</p>
			<div class="flex items-center gap-2">
				<LoadingIndicator
					v-if="loading"
					class="h-4 w-4 text-ink-gray-5"
				/>
				<TabButtons
					v-if="preview.html_ar"
					v-model="lang"
					:buttons="LANGS"
				/>
			</div>
		</div>
		<div
			v-if="preview.subject"
			class="min-w-0"
		>
			<p
				v-if="preview.sender"
				class="truncate text-p-sm font-medium text-ink-gray-8"
			>
				{{ preview.sender }}
			</p>
			<p class="truncate text-p-sm text-ink-gray-7">
				{{ preview.subject }}
			</p>
		</div>
		<ErrorMessage
			v-if="preview.error"
			:message="preview.error"
		/>
		<p
			v-else-if="preview.message"
			class="rounded border border-dashed border-outline-gray-2 p-4 text-p-sm text-ink-gray-5"
		>
			{{ preview.message }}
		</p>
		<iframe
			v-else
			title="Email preview"
			sandbox=""
			:srcdoc="html"
			class="h-[32rem] w-full rounded border border-outline-gray-2 bg-surface-white"
		/>
		<p class="text-p-sm text-ink-gray-5">
			{{ note }}
		</p>
	</div>
</template>

<script setup>
import { computed, ref } from "vue";
import { ErrorMessage, LoadingIndicator, TabButtons } from "frappe-ui";

const LANGS = [
	{ label: "EN", value: "en" },
	{ label: "عربي", value: "ar" },
];

const props = defineProps({
	// { html, html_ar, subject, sender, message, error, docname } from preview_notification
	preview: { type: Object, required: true },
	loading: { type: Boolean, default: false },
	note: {
		type: String,
		default:
			"The preview shows the draft in the editor, not what is saved. No buttons: an Email Notification has no task to complete, so readers act in ERPNext.",
	},
});

const lang = ref("en");
const html = computed(() => (lang.value === "ar" && props.preview.html_ar) || props.preview.html);
</script>
