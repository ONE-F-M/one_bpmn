<template>
	<div class="flex min-w-0 flex-col gap-2">
		<div class="flex items-center justify-between gap-2">
			<p class="text-sm font-medium text-ink-gray-8">
				{{ preview.docname ? `Live preview · ${preview.docname}` : "Live preview" }}
			</p>
			<LoadingIndicator
				v-if="loading"
				class="h-4 w-4 text-ink-gray-5"
			/>
		</div>
		<p
			v-if="preview.subject"
			class="truncate text-p-sm text-ink-gray-7"
		>
			{{ preview.subject }}
		</p>
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
			:srcdoc="preview.html"
			class="h-[32rem] w-full rounded border border-outline-gray-2 bg-surface-white"
		/>
		<p class="text-p-sm text-ink-gray-5">
			The preview shows the draft in the editor, not what is saved. No buttons: an Email Notification has no task
			to complete, so readers act in ERPNext.
		</p>
	</div>
</template>

<script setup>
import { ErrorMessage, LoadingIndicator } from "frappe-ui";

defineProps({
	// { html, subject, message, error, docname } from preview_notification
	preview: { type: Object, required: true },
	loading: { type: Boolean, default: false },
});
</script>
