<script setup>
import { inject, toRef } from "vue";
import BpmnEditor from "@/components/Editor/BpmnEditor/BpmnEditor.vue";
import CompareDialog from "@/components/Modals/CompareModal/CompareModal.vue";
import EditorTabs from "@/components/Editor/EditorTabs/EditorTabs.vue";
import { Icon } from "@iconify/vue";
import VersionDiffDialog from "@/components/Modals/VersionDiffModal/VersionDiffModal.vue";
import { PROCESS_KEY } from "@/composables/Process/useProcessState";

const pc = inject(PROCESS_KEY);
const compact = toRef(pc.props, "compact");
const process = toRef(pc.props, "process");
const {
	activeDiagramName,
	activeVersionName,
	canEditActiveDiagram,
	compareDialogRef,
	diagrams,
	editorRef,
	handleDeleteTab,
	handleFitToScreen,
	handleResetZoom,
	handleZoomIn,
	handleZoomOut,
	isEditable,
	isMobile,
	loading,
	namedVersionTabs,
	onConfirmScriptDelete,
	onDiagramChanged,
	onEditorReady,
	onLaunchCallActivityEditor,
	onLaunchCallActivitySearch,
	onLaunchDmnEditor,
	onLaunchEmailNotificationEditor,
	onLaunchMarkdownEditor,
	onLaunchNotificationEditor,
	onLaunchNotifyAssigneeEditor,
	onLaunchScriptEditor,
	onReassignChanged,
	onSelectTab,
	onZoomChanged,
	openCompareDialog,
	openTabs,
	openVersionPicker,
	reassignMode,
	renameProcessModel,
	saveStatusColor,
	saveStatusText,
	selectVersion,
	showNotification,
	versionDiffRef,
	zoomLevel,
} = pc;
</script>

<template>
	<!-- Main Content -->
	<div :class="['flex-1 flex flex-col', isMobile ? '' : 'overflow-hidden']">
		<!-- Canvas Area -->
		<div :class="['flex-1 flex', isMobile ? '' : 'overflow-hidden']">
			<!-- Canvas -->

			<div class="flex-1 relative">
				<!-- Loading state -->
				<div v-if="loading" class="flex items-center justify-center h-full bg-gray-100">
					<div class="text-center">
						<div
							class="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-700 mx-auto mb-4"
						></div>
						<p class="text-gray-500">Loading...</p>
					</div>
				</div>

				<!-- Single long-lived modeler instance; mounts on first diagram selection.
			     Clipboard state (globalClipboardData) lives at module scope so it
			     survives unmount - v-if is safe here and defers the heavy init. -->
				<BpmnEditor
					v-if="activeDiagramName"
					ref="editorRef"
					class="absolute inset-0"
					:save-status-text="saveStatusText"
					:save-status-color="saveStatusColor"
					:readonly="!canEditActiveDiagram || !!activeVersionName"
					:reassign-mode="reassignMode && !activeVersionName"
					:model-name="activeDiagramName"
					:process="process"
					@ready="onEditorReady"
					@changed="onDiagramChanged"
					@reassign-changed="onReassignChanged"
					@zoom-changed="onZoomChanged"
					@launch-script-editor="onLaunchScriptEditor"
					@confirm-script-delete="onConfirmScriptDelete"
					@launch-markdown-editor="onLaunchMarkdownEditor"
					@launch-callactivity-editor="onLaunchCallActivityEditor"
					@launch-callactivity-search="onLaunchCallActivitySearch"
					@launch-notification-editor="onLaunchNotificationEditor"
					@launch-dmn-editor="onLaunchDmnEditor"
					@launch-notify-assignee-editor="onLaunchNotifyAssigneeEditor"
					@launch-email-notification-editor="onLaunchEmailNotificationEditor"
				/>

				<!-- No-diagram placeholder: only shown when not loading and no diagram is selected -->
				<div
					v-if="!loading && !activeDiagramName"
					class="flex items-center justify-center h-full bg-gray-100"
				>
					<div class="text-center">
						<div class="text-gray-400 mb-6">
							<Icon icon="lucide:layout-grid" class="w-20 h-20 mx-auto" />
						</div>
						<p class="text-gray-500 text-lg mb-6">No process map selected</p>
						<p v-if="isEditable" class="text-sm text-gray-400 max-w-sm mx-auto">
							Process maps are created through the Process Implementation process —
							they cannot be added from the editor.
						</p>
						<p v-else class="text-sm text-gray-400">
							<Icon icon="lucide:lock" class="w-4 h-4 inline mr-1" />
							Process is locked. Create a Process Implementation and get it actioned
							to "Active" state to enable editing.
						</p>
					</div>
				</div>
			</div>
		</div>

		<!-- Tab Bar (hidden in compact mode - uses toolbar dropdown instead) -->
		<div
			v-if="openTabs.length > 0 && !compact"
			class="relative z-10 flex items-center justify-between bg-white border-t border-gray-200 min-h-[40px]"
		>
			<EditorTabs
				:tabs="openTabs"
				:all-tabs="diagrams"
				:active-tab="activeVersionName ? null : activeDiagramName"
				:readonly="!isEditable"
				:versions="namedVersionTabs"
				:active-version="activeVersionName"
				class="flex-1 min-w-0"
				@select-tab="onSelectTab"
				@rename-tab="renameProcessModel"
				@delete-tab="handleDeleteTab"
				@select-version="selectVersion"
				@compare="openCompareDialog"
			/>

			<!-- Zoom Controls -->
			<div class="hidden sm:flex items-center gap-1 px-3 py-2 border-l border-gray-300">
				<button
					class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
					title="Zoom Out (Ctrl+-)"
					@click="handleZoomOut"
				>
					<Icon icon="lucide:minus" class="w-4 h-4" />
				</button>
				<button
					class="px-2 py-1 rounded hover:bg-gray-300 text-gray-700 text-sm font-medium min-w-[50px] text-center transition-colors"
					title="Reset Zoom"
					@click="handleResetZoom"
				>
					{{ zoomLevel }}%
				</button>
				<button
					class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
					title="Zoom In (Ctrl++)"
					@click="handleZoomIn"
				>
					<Icon icon="lucide:plus" class="w-4 h-4" />
				</button>
				<button
					class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors ml-1"
					title="Fit to Screen"
					@click="handleFitToScreen"
				>
					<Icon icon="lucide:maximize-2" class="w-4 h-4" />
				</button>
			</div>
		</div>
	</div>

	<!-- Version Comparison Dialogs (extracted component) -->
	<VersionDiffDialog
		ref="versionDiffRef"
		:diagram-name="activeDiagramName"
		@error="(e) => showNotification(e.title, e.message, e.theme)"
	/>

	<!-- Compare versions dialog (named version vs latest), opened by the
     compare icon in the bottom bar -->
	<CompareDialog
		ref="compareDialogRef"
		:model-name="activeDiagramName"
		@error="(e) => showNotification(e.title, e.message, e.theme)"
		@compare-deployed="openVersionPicker"
	/>
</template>
