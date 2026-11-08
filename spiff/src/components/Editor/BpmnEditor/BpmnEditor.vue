<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<BpmnEditorToolbar />

		<div :class="['flex-1 flex relative', isMobile ? 'overflow-visible' : 'overflow-hidden']">
			<!-- BPMN Canvas -->
			<div
				ref="container"
				:class="['bpmn-canvas flex-1 min-w-0', { 'bpmn-canvas--readonly': readonly, 'comment-mode-active': isCommentMode }]"
				@contextmenu.prevent
			></div>

			<BpmnProsAlly />

			<BpmnInlineComment />

			<BpmnMobileToolbar />

			<BpmnPropertiesPanel />

			<BpmnCommentPanel />

			<!-- Desktop: Floating Properties Panel Toggle Handle
			     Placed OUTSIDE the panel container to avoid overflow-hidden clipping.
			     Positioned at the panel's left edge using a dynamic right offset. -->
			<button
				v-if="!isMobile && showPropertiesPanel"
				@click="togglePropertiesCollapse"
				class="absolute top-1/2 -translate-y-1/2 w-6 h-12 bg-white border border-gray-200 rounded-l-lg shadow-md hidden md:flex items-center justify-center text-gray-500 hover:text-gray-900 transition-all duration-300 z-[65]"
				:style="{ right: (propertiesCollapsed ? 0 : 384) + 'px' }"
				:title="propertiesCollapsed ? 'Expand Properties Panel' : 'Collapse Properties Panel'"
			>
				<Icon :icon="propertiesCollapsed ? 'lucide:chevron-left' : 'lucide:chevron-right'" class="w-4 h-4" />
			</button>

			<!-- Comment Mode Instruction Banner -->
			<transition name="fade">
				<div 
					v-if="isCommentMode && !showCommentDialog"
					class="absolute top-4 left-1/2 -translate-x-1/2 z-[100] bg-blue-600 text-white px-4 py-2 rounded-full shadow-lg flex items-center gap-3"
				>
					<Icon icon="lucide:info" class="w-4 h-4" />
					<span class="text-sm font-medium">Click on any shape to add a comment</span>
					<button 
						@click="toggleCommentMode"
						class="ml-2 p-1 hover:bg-blue-500/20 rounded-full"
					>
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>
			</transition>
		</div>

		<BpmnCommentDialogs />
		<BpmnContextMenu />
		<BpmnMessageDialog />

		<!-- AI Agent Task / AI Task Selector config modal -->
		<AIAgentConfigModal
			v-if="aiAgentModal.element"
			v-show="aiAgentModal.show"
			:key="`${aiAgentModal.element.id}:${aiAgentModal.mode}`"
			:element="aiAgentModal.element"
			:modeler="ed.modeler"
			:mode="aiAgentModal.mode"
			:readonly="readonly"
			@hide="aiAgentModal.show = false"
			@close="aiAgentModal.element = null"
		/>

		<BpmnDocuPanel />
	</div>
</template>

<script setup>
import { provide } from "vue";
import { Icon } from "@iconify/vue";
import AIAgentConfigModal from "@/components/Modals/AIAgentConfigModal/AIAgentConfigModal.vue";
import { useEditorModeler } from "@/composables/useEditorModeler";
import BpmnEditorToolbar from "../BpmnEditorToolbar/BpmnEditorToolbar.vue";
import BpmnProsAlly from "../BpmnProsAlly/BpmnProsAlly.vue";
import BpmnInlineComment from "../BpmnInlineComment/BpmnInlineComment.vue";
import BpmnMobileToolbar from "../BpmnMobileToolbar/BpmnMobileToolbar.vue";
import BpmnPropertiesPanel from "../BpmnPropertiesPanel/BpmnPropertiesPanel.vue";
import BpmnCommentPanel from "../BpmnCommentPanel/BpmnCommentPanel.vue";
import BpmnCommentDialogs from "../BpmnCommentDialogs/BpmnCommentDialogs.vue";
import BpmnDocuPanel from "../BpmnDocuPanel/BpmnDocuPanel.vue";
import BpmnContextMenu from "../BpmnContextMenu/BpmnContextMenu.vue";
import BpmnMessageDialog from "../BpmnMessageDialog/BpmnMessageDialog.vue";
import { createEditorContext, EDITOR_KEY } from "@/composables/useEditorState";
import { useEditorPanels } from "@/composables/useEditorPanels";
import { useEditorDialogs } from "@/composables/useEditorDialogs";
import { useEditorComments } from "@/composables/useEditorComments";
import { useEditorTimeline } from "@/composables/useEditorTimeline";
import { useEditorInlineComment } from "@/composables/useEditorInlineComment";
import { useEditorTouch } from "@/composables/useEditorTouch";
import { useEditorElements } from "@/composables/useEditorElements";
import { useEditorLint } from "@/composables/useEditorLint";
import { useEditorCanvas } from "@/composables/useEditorCanvas";
import { useEditorCopyPaste } from "@/composables/useEditorCopyPaste";
import { useEditorSpiffEvents } from "@/composables/useEditorSpiffEvents";
import { useEditorDocu } from "@/composables/useEditorDocu";
import { useEditorXml } from "@/composables/useEditorXml";
import { useEditorReadonly } from "@/composables/useEditorReadonly";

const props = defineProps({
	saveStatusText: {
		type: String,
		default: ""
	},
	saveStatusColor: {
		type: String,
		default: ""
	},
	readonly: {
		type: Boolean,
		default: false
	},
	// "Release Property Panel" mode - while readonly, re-enables the properties
	// panel for flow objects, minus script tasks, AI Agent tasks and the
	// attributes that would break the map. A sequence flow's condition and name
	// are editable. Structural editing (moving, deleting, connecting) stays
	// blocked.
	reassignMode: {
		type: Boolean,
		default: false
	},
	modelName: {
		type: String,
		default: ""
	},
	process: {
		type: String,
		default: ""
	}
});

const emit = defineEmits([
	"ready",
	"changed",
	"zoom-changed",
	"launch-script-editor",
	"confirm-script-delete",
	"launch-markdown-editor",
	"launch-callactivity-editor",
	"launch-callactivity-search",
	"launch-notification-editor",
	"launch-dmn-editor",
	"launch-notify-assignee-editor",
	"launch-email-notification-editor",
	"reassign-changed",
]);

const ed = createEditorContext(props, emit);
provide(EDITOR_KEY, ed);
useEditorPanels(ed);
useEditorDialogs(ed);
useEditorComments(ed);
useEditorTimeline(ed);
useEditorInlineComment(ed);
useEditorTouch(ed);
useEditorElements(ed);
useEditorLint(ed);
useEditorCanvas(ed);
useEditorCopyPaste(ed);
useEditorSpiffEvents(ed);
useEditorDocu(ed);
useEditorXml(ed);
useEditorReadonly(ed);
useEditorModeler(ed);

const {
	addOverlay,
	addStickyNote,
	aiAgentModal,
	clearAllOverlays,
	clearElementColor,
	comments,
	container,
	deleteSelected,
	fitToScreen,
	getRawLintIssues,
	getSelectedElements,
	getXML,
	getZoomLevel,
	isCommentMode,
	isMobile,
	loadXML,
	propertiesCollapsed,
	redo,
	removeOverlay,
	removeOverlaysByElement,
	resetZoom,
	setElementColor,
	setProcessName,
	showCommentDialog,
	showPropertiesPanel,
	showProsAllyPanel,
	showTimeline,
	toggleCommentMode,
	togglePropertiesCollapse,
	toggleTimeline,
	undo,
	updateCalledElement,
	zoomIn,
	zoomOut
} = ed;

defineExpose({
	getXML,
	getRawLintIssues,
	loadXML,
	setProcessName,
	undo,
	redo,
	deleteSelected,
	addStickyNote,
	zoomIn,
	zoomOut,
	resetZoom,
	fitToScreen,
	getZoomLevel,
	// Overlay API
	addOverlay,
	removeOverlay,
	removeOverlaysByElement,
	clearAllOverlays,
	// Element Color API
	setElementColor,
	clearElementColor,
	getSelectedElements,
	// Call Activity API
	updateCalledElement,
	// Properties Panel API
	togglePropertiesCollapse,
	toggleTimeline,
	// Comment Panel state (readable from Editor.vue)
	showTimeline,
	showPropertiesPanel,
	propertiesCollapsed,
	comments,
	showProsAllyPanel,
});
</script>

<style src="./BpmnEditor.css"></style>
