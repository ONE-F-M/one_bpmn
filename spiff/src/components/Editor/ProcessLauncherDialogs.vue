<script setup>
import { inject } from "vue";
import CallActivitySearchDialog from "@/components/Modals/CallActivitySearchModal.vue";
import EmailNotificationEditorDialog from "@/components/Modals/EmailNotificationEditorModal.vue";
import NotificationLinkDialog from "@/components/Modals/NotificationLinkModal.vue";
import NotifyAssigneeEditorDialog from "@/components/Modals/NotifyAssigneeEditorModal.vue";
import { TextEditor } from "frappe-ui";
import { PROCESS_KEY } from "@/composables/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	activeDiagramName,
	callActivitySearchEvent,
	emailNotificationValues,
	isExecutable,
	markdownEditorContent,
	notifyAssigneeDoctype,
	notifyAssigneeTaskActions,
	notifyAssigneeTaskName,
	notifyAssigneeValues,
	onCallActivitySelected,
	onCancelCallActivitySearch,
	onSaveEmailNotification,
	onSaveNotifyAssigneeBody,
	saveMarkdown,
	showCallActivitySearchDialog,
	showEmailNotificationDialog,
	showMarkdownEditorDialog,
	showNotifyAssigneeDialog,
} = pc;
</script>

<template>
	<!-- Call Activity Search Dialog -->
	<CallActivitySearchDialog
		v-model="showCallActivitySearchDialog"
		:caller-executable="isExecutable"
		:search-event="callActivitySearchEvent"
		@select="onCallActivitySelected"
		@cancel="onCancelCallActivitySearch"
	/>

	<!-- Markdown Editor Dialog -->
	<Dialog
		v-model="showMarkdownEditorDialog"
		:options="{ title: 'Edit Instructions (Markdown)', size: '4xl' }"
	>
		<template #body-content>
			<div class="space-y-3">
				<div class="text-sm text-gray-500">
					Edit the markdown content for this element's instructions.
				</div>
				<TextEditor
					editor-class="prose-sm min-h-[16rem] border rounded-b-lg border-t-0 p-3"
					:content="markdownEditorContent"
					placeholder="Type instructions here..."
					:bubble-menu="true"
					:fixed-menu="true"
					@change="(val) => (markdownEditorContent = val)"
				/>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="showMarkdownEditorDialog = false">Cancel</Button>
				<Button variant="solid" @click="saveMarkdown">Save</Button>
			</div>
		</template>
	</Dialog>

	<!-- Notification Selector/Creator Dialog (Send Task) -->
	<NotificationLinkDialog />

	<!-- Notify Assignee Editor Dialog (User Task) -->
	<NotifyAssigneeEditorDialog
		v-model="showNotifyAssigneeDialog"
		:initial-values="notifyAssigneeValues"
		:doctype="notifyAssigneeDoctype"
		:task-name="notifyAssigneeTaskName"
		:task-actions="notifyAssigneeTaskActions"
		:process-model="activeDiagramName"
		@save="onSaveNotifyAssigneeBody"
	/>

	<!-- Email Notification Editor Dialog (Service Task) -->
	<EmailNotificationEditorDialog
		v-model="showEmailNotificationDialog"
		:initial-values="emailNotificationValues"
		:process-model="activeDiagramName"
		@save="onSaveEmailNotification"
	/>
</template>

<style scoped src="./processPageDialogs.css"></style>
