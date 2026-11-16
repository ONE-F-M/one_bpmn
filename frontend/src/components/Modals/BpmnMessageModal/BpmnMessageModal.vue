<script setup>
import { inject } from "vue";
import { EDITOR_KEY } from "@/composables/Editor/useEditorState";

const ed = inject(EDITOR_KEY);
const { messageDialog, onMessageDialogSave } = ed;
</script>

<template>
	<!-- Message name dialog -->
	<Dialog
		v-model="messageDialog.show"
		:options="{
			title: messageDialog.isEdit ? 'Edit Message' : 'New Message',
			size: 'sm',
			actions: [
				{
					label: messageDialog.isEdit ? 'Save' : 'Create',
					variant: 'solid',
					disabled: !messageDialog.name?.trim(),
					onClick: ({ close }) => onMessageDialogSave(close),
				},
			],
		}"
	>
		<template #body-content>
			<div class="space-y-4">
				<div>
					<label class="block text-sm font-medium text-gray-700 mb-1"
						>Message Name</label
					>
					<input
						v-model="messageDialog.name"
						type="text"
						placeholder="e.g. GitHub: PR Merged"
						class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
						@keydown.enter="
							messageDialog.name?.trim() &&
							onMessageDialogSave(() => (messageDialog.show = false))
						"
					/>
					<p class="mt-1 text-xs text-gray-500">
						The name must match what the external system sends.
					</p>
				</div>
			</div>
		</template>
	</Dialog>
</template>
