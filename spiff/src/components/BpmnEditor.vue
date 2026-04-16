<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<!-- Toolbar (moved natively to parent Editor.vue's header) -->
		<div ref="toolbarEl" v-show="isMounted" class="flex items-center gap-1.5 w-full h-full text-gray-700 overflow-x-auto scrollbar-hide flex-nowrap min-w-0 pr-2">
			<template v-if="!readonly">
				<!-- Undo/Redo buttons -->
				<button
					@click="undo"
					title="Undo (Ctrl+Z)"
					:disabled="!canUndo"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						canUndo
							? 'hover:bg-gray-100 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
				>
					<Icon icon="lucide:undo-2" class="w-4 h-4" />
				</button>
				<button
					@click="redo"
					title="Redo (Ctrl+Y)"
					:disabled="!canRedo"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						canRedo
							? 'hover:bg-gray-100 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
				>
					<Icon icon="lucide:redo-2" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Delete button -->
				<button
					@click="deleteSelected"
					title="Delete (Del)"
					class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
				>
					<Icon icon="lucide:trash-2" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Sticky Note button -->
				<button
					@click="addStickyNote"
					title="Add Sticky Note"
					class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
				>
					<Icon icon="lucide:sticky-note" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Comment Tool button -->
				<button
					@click="toggleCommentMode"
					title="Comment Tool"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						isCommentMode
							? 'bg-blue-100 text-blue-700 shadow-sm'
							: 'hover:bg-gray-100 text-gray-700'
					]"
				>
					<Icon icon="lucide:message-square" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Formatting Toolbar -->
				<FormattingToolbar
					:selectedElements="selectedElements"
					:modeler="modelerInstance"
					class="shrink-0"
				/>
			</template>

			<!-- Read-only indicator -->
			<div v-if="readonly" class="flex items-center gap-1.5 text-gray-400 text-sm">
				<Icon icon="lucide:lock" class="w-4 h-4" />
				<span>View Only</span>
			</div>


			<div class="flex-1 min-w-4 flex items-center justify-end px-3">
				<div v-if="saveStatusText && !readonly" class="text-sm font-medium transition-colors mr-2" :class="saveStatusColor">
					{{ saveStatusText }}
				</div>
			</div>
		</div>



		<!-- Main Content Area -->
		<div :class="['flex-1 flex relative', isMobile ? 'overflow-visible' : 'overflow-hidden']">
			<!-- BPMN Canvas -->
			<div
				ref="container"
				:class="['bpmn-canvas flex-1', { 'bpmn-canvas--readonly': readonly, 'comment-mode-active': isCommentMode }]"
				@contextmenu.prevent
				@dragover.prevent="!readonly && handleDragOver($event)"
				@drop.prevent="!readonly && handleDrop($event)"
			></div>

			<!-- ── Mobile Floating Toolbar (Undo/Redo/Delete/Format) ── -->
			<transition name="fade">
				<div
					v-if="isMobile && !readonly && isMounted"
					class="fixed bottom-14 left-1/2 -translate-x-1/2 z-[45] bg-white/95 backdrop-blur rounded-full shadow-lg border border-gray-200 flex items-center gap-1 px-2 py-1.5"
				>
					<button
						@click="undo"
						:disabled="!canUndo"
						:class="['min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors', canUndo ? 'text-gray-700 active:bg-gray-100' : 'text-gray-300']"
					>
						<Icon icon="lucide:undo-2" class="w-5 h-5" />
					</button>
					<button
						@click="redo"
						:disabled="!canRedo"
						:class="['min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors', canRedo ? 'text-gray-700 active:bg-gray-100' : 'text-gray-300']"
					>
						<Icon icon="lucide:redo-2" class="w-5 h-5" />
					</button>
					<div class="w-px h-6 bg-gray-200 mx-0.5"></div>
					<button
						@click="deleteSelected"
						class="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-gray-700 active:bg-gray-100 transition-colors"
					>
						<Icon icon="lucide:trash-2" class="w-5 h-5" />
					</button>
					<div class="w-px h-6 bg-gray-200 mx-0.5"></div>
					<!-- Format button — opens formatting popover -->
					<div class="relative">
						<button
							@click="showMobileFormatPopover = !showMobileFormatPopover"
							:class="['min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors', showMobileFormatPopover ? 'bg-blue-100 text-blue-700' : 'text-gray-700 active:bg-gray-100']"
						>
							<Icon icon="lucide:palette" class="w-5 h-5" />
						</button>
						<!-- Format popover -->
						<transition name="fade">
							<div
								v-if="showMobileFormatPopover"
								v-click-outside="() => showMobileFormatPopover = false"
								class="absolute bottom-full right-0 mb-2 bg-white border border-gray-200 rounded-xl shadow-xl p-2 z-[100] min-w-[280px]"
							>
								<FormattingToolbar
									:selectedElements="selectedElements"
									:modeler="modelerInstance"
								/>
							</div>
						</transition>
					</div>
				</div>
			</transition>

			<!-- ── Properties Panel ── -->
			<!-- Mobile: backdrop overlay -->
			<transition name="fade">
				<div
					v-if="showPropertiesPanel && isMobile"
					class="fixed inset-0 bg-black/30 z-[58] backdrop-blur-sm"
					@click="showPropertiesPanel = false"
				></div>
			</transition>

			<transition :name="isMobile ? 'slide-up' : 'slide-right'">
				<div
					v-show="showPropertiesPanel"
					:class="[
						'properties-panel-container bg-white z-[60] transition-all duration-300 ease-in-out flex flex-col',
						// Mobile: bottom sheet
						isMobile
							? 'fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 max-h-[85vh] overflow-hidden'
							: 'absolute inset-y-0 right-0 border-l border-gray-200 md:relative',
						// Desktop: collapse behavior
						!isMobile && propertiesCollapsed 
							? 'w-[48px] overflow-hidden' 
							: !isMobile ? 'w-full md:w-96 overflow-auto' : '',
						{ 'properties-panel--readonly': readonly }
					]"
					:style="isDragging ? { transform: `translateY(${dragOffset}px)`, transition: 'none', willChange: 'transform' } : {}"
				>
					<!-- Mobile: Drag handle + close button -->
					<div v-if="isMobile" class="flex items-center justify-between px-4 pt-3 pb-2 shrink-0">
						<div class="flex-1 flex justify-center">
							<div ref="dragHandleRef" class="w-10 h-1 bg-gray-300 rounded-full cursor-grab active:cursor-grabbing"></div>
						</div>
						<button
							@click="showPropertiesPanel = false"
							class="p-1.5 -mr-1 rounded-full hover:bg-gray-100 text-gray-500 transition-colors"
						>
							<Icon icon="lucide:x" class="w-5 h-5" />
						</button>
					</div>

					<!-- Inner container -->
					<div 
						ref="propertiesContainer"
						:class="[
							'flex-1 flex flex-col min-w-0 transition-opacity duration-200 overflow-y-auto mobile-safe-area-bottom',
							!isMobile && propertiesCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'
						]"
					>
						<!-- Content is injected here by bpmn-js-properties-panel -->
					</div>

					<!-- Desktop: Floating Collapse/Expand Handle -->
					<button
						v-if="!isMobile"
						@click="togglePropertiesCollapse"
						class="absolute left-0 top-1/2 -translate-x-1/2 -translate-y-1/2 w-6 h-12 bg-white border border-gray-200 rounded-l-lg shadow-md flex items-center justify-center text-gray-500 hover:text-gray-900 transition-all z-[70] hidden md:flex"
						:title="propertiesCollapsed ? 'Expand' : 'Collapse'"
					>
						<Icon :icon="propertiesCollapsed ? 'lucide:chevron-left' : 'lucide:chevron-right'" class="w-4 h-4" />
					</button>
					
					<!-- Desktop: Sidebar-style collapse placeholder -->
					<div 
						v-if="!isMobile && propertiesCollapsed"
						class="absolute inset-0 flex flex-col items-center pt-4 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors"
						@click="togglePropertiesCollapse"
					>
						<Icon icon="lucide:settings" class="w-5 h-5 text-gray-400 mb-4 animate-pulse" />
						<div class="w-px h-full bg-gray-200"></div>
					</div>
				</div>
			</transition>

			<!-- Comment Mode Instruction Banner -->
			<transition name="fade">
				<div 
					v-if="isCommentMode && !showCommentDialog"
					class="absolute top-4 left-1/2 -translate-x-1/2 z-[100] bg-blue-600 text-white px-4 py-2 rounded-full shadow-lg flex items-center gap-3"
				>
					<Icon icon="lucide:info" class="w-4 h-4" />
					<span class="text-sm font-medium">Click on any shape or the canvas to add a comment</span>
					<button 
						@click="toggleCommentMode"
						class="ml-2 p-1 hover:bg-blue-500/20 rounded-full"
					>
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>
			</transition>
		</div>
		
		<!-- Comment Dialog -->
		<Dialog v-model="showCommentDialog" :options="{ title: 'Add Comment' }">
			<template #body-content>
				<div class="space-y-4">
					<div v-if="activeCommentElement" class="text-xs text-gray-500 bg-gray-50 p-2 rounded border border-gray-100 italic">
						Attaching to: {{ activeCommentElement.businessObject?.name || activeCommentElement.id }}
					</div>
					
					<div class="relative">
						<FormControl
							label="Comment"
							type="textarea"
							v-model="commentFormData.text"
							@keyup="handleCommentInput"
							@click="handleCommentInput"
							:required="true"
							placeholder="What's on your mind?"
						/>
						<div
							v-if="showMentionDropdown"
							v-click-outside="() => { showMentionDropdown = false; }"
							class="absolute z-[120] w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1 left-0 top-full mt-1"
						>
							<div
								v-for="u in mentionSuggestions"
								:key="u.value"
								@click="selectMention(u)"
								class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
							>
								<span>{{ u.label }}</span>
							</div>
							<div v-if="mentionSuggestions.length === 0" class="px-3 py-1.5 text-xs text-gray-400 italic">
								No users found
							</div>
						</div>
					</div>
					
					<div class="flex items-center gap-4">
						<div class="flex-1">
							<div class="space-y-1">
								<label class="block text-xs font-medium text-gray-700">Assign To</label>
								<div class="relative">
									<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
									<input
										v-model="userSearchQuery"
										type="text"
										placeholder="Search users..."
										class="w-full pl-9 pr-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
										@focus="showUserDropdown = true"
									/>
									<div 
										v-if="showUserDropdown && filteredUsers.length > 0" 
										v-click-outside="() => showUserDropdown = false"
										class="absolute z-[110] w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1"
									>
										<div
											v-for="u in filteredUsers"
											:key="u.value"
											@click="commentFormData.assigned_to = u.value; userSearchQuery = u.label; showUserDropdown = false"
											class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
										>
											<span>{{ u.label }}</span>
											<Icon v-if="commentFormData.assigned_to === u.value" icon="lucide:check" class="w-3.5 h-3.5 text-blue-600" />
										</div>
									</div>
									<div v-else-if="showUserDropdown && userSearchQuery && filteredUsers.length === 0" class="absolute z-[110] w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg p-3 text-xs text-gray-400 italic">
										No users found
									</div>
								</div>
							</div>
						</div>
						<div class="pt-6">
							<label class="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-700">
								<input
									type="checkbox"
									v-model="commentFormData.is_task"
									class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
								/>
								Actionable Task
							</label>
						</div>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showCommentDialog = false">Cancel</Button>
					<Button variant="solid" @click="submitComment" :disabled="!commentFormData.text">Post Comment</Button>
				</div>
			</template>
		</Dialog>
		<!-- View Comments Dialog -->
		<Dialog v-model="showViewCommentsDialog" :options="{ title: 'Comments', size: 'md' }">
			<template #body-content>
				<div class="space-y-4 max-h-[60vh] overflow-y-auto pr-2 pb-2">
					<div 
						v-for="comment in selectedElementComments" 
						:key="comment.name"
						class="p-3 bg-white border border-gray-100 rounded-lg shadow-sm space-y-2"
					>
						<div class="flex items-center justify-between">
							<div class="flex items-center gap-2">
								<Avatar :label="comment.author" size="sm" />
								<span class="text-xs font-semibold text-gray-700">{{ comment.author }}</span>
							</div>
							<span class="text-[10px] text-gray-400 italic">
								{{ new Date(comment.creation.replace(" ", "T").replace(/(\.\d{3})\d+$/, "$1")).toLocaleString() }}
							</span>
						</div>
						
						<p class="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{{ comment.comment }}</p>
						
						<div v-if="comment.is_task" class="flex items-center justify-between pt-2 border-t border-gray-50 mt-2">
							<div class="flex items-center gap-2">
								<Badge 
									:theme="comment.status === 'Resolved' ? 'green' : 'orange'" 
									:label="comment.status" 
									size="sm" 
								/>
								<span v-if="comment.assigned_to" class="text-[10px] text-gray-500">
									Assigned to: {{ comment.assigned_to }}
								</span>
							</div>
							
							<Button 
								v-if="comment.status === 'Open'" 
								variant="subtle" 
								size="sm" 
								@click="resolveComment(comment)"
								class="text-green-600 hover:bg-green-50"
							>
								Resolve
							</Button>
						</div>
					</div>
					
					<div v-if="selectedElementComments.length === 0" class="text-center py-8 text-gray-400 italic text-sm">
						No comments yet.
					</div>
				</div>
			</template>
			<template #actions>
				<div class="flex justify-end">
					<Button variant="subtle" @click="showViewCommentsDialog = false">Close</Button>
				</div>
			</template>
		</Dialog>

		<!-- Right-Click Context Menu -->
		<div
			v-if="showContextMenu"
			v-click-outside="() => showContextMenu = false"
			class="fixed z-[200] bg-white border border-gray-200 rounded-lg shadow-xl py-1 min-w-[180px]"
			:style="{ left: contextMenuPosition.x + 'px', top: contextMenuPosition.y + 'px' }"
		>
			<button
				v-if="canAddComment"
				@click="addCommentFromContextMenu"
				class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-blue-50 transition-colors"
			>
				<Icon icon="lucide:message-square-plus" class="w-4 h-4" />
				Add Comment
			</button>
			<button
				v-if="contextMenuElementCommentCount > 0"
				@click="viewCommentsFromContextMenu"
				class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-blue-50 transition-colors"
			>
				<Icon icon="lucide:messages-square" class="w-4 h-4" />
				View Comments ({{ contextMenuElementCommentCount }})
			</button>
		</div>
	</div>
</template>

<script setup>
import { ref, shallowRef, onMounted, onBeforeUnmount, watch, computed, nextTick } from "vue";
import { frappeRequest } from "frappe-ui";
import {
	injectProcessNameField,
	reinjectIfCalledElementChanged,
	removeProcessNameField,
	cancelPendingInjection,
} from "@/composables/useCallActivityName";
import { Icon } from "@iconify/vue";
import { useWindowSize } from "@/composables/useWindowSize";
import { useBottomSheet } from "@/composables/useBottomSheet";
// Custom Shapes - DISABLED (see DEVELOPMENT_CONTEXT.md)
// import CustomShapesModule, { customShapeSvgStore } from "@/bpmn";
import FormattingToolbar from "@/components/FormattingToolbar.vue";
import { initModeler } from "@/composables/useModelerInit";
import { useBpmnContextMenu } from "@/composables/useBpmnContextMenu";
// Properties panel
import {
	BpmnPropertiesPanelModule,
	BpmnPropertiesProviderModule,
} from "bpmn-js-properties-panel";

// SpiffWorkflow extensions (ESM from forked repo)
import spiffworkflow, { spiffModdleExtension } from "bpmn-js-spiffworkflow";

// Minimap for diagram navigation - DISABLED
// import minimapModule from "diagram-js-minimap";

// i18n for translations
import translateModule from "@/i18n";

// Custom modeling rules
import customRulesModule from "@/rules";

// Custom text styling module
import { customTextStyleModule, stickyNoteModule } from "@/renderers";

// Native system-clipboard module — enables copy/paste across browser tabs.
// Inlined from https://github.com/nikku/bpmn-js-native-copy-paste (MIT)
// because the npm package requires bpmn-js >= 18 (project uses 17).
import nativeCopyPasteModule from "@/utils/nativeCopyPaste";
import clipboardModule from "@/utils/clipboard";

// Custom moddle extension for text style attributes
import customTextStyleModdle from "@/moddle/customTextStyleModdle";

// Task resize + auto-label-fit module
import resizeModule from "@/resize";

import userTaskPropertiesProviderModule from "@/bpmn/userTaskPropertiesProvider";
import sendTaskPropertiesProviderModule from "@/bpmn/sendTaskPropertiesProvider";
import serviceTaskPropertiesProviderModule from "@/bpmn/serviceTaskPropertiesProvider";
import scriptTaskPropertiesProviderModule from "@/bpmn/scriptTaskPropertiesProvider";
import intermediateEventPropertiesProviderModule from "@/bpmn/intermediateEventPropertiesProvider";
import timerPropertiesProviderModule from "@/bpmn/timerPropertiesProvider";
import startEventPropertiesProviderModule from "@/bpmn/startEventPropertiesProvider";
import conditionalStartEventPropertiesProviderModule from "@/bpmn/conditionalStartEventPropertiesProvider";

// bpmnlint — diagram validation
import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/linting/bpmnlintrc.js";

// Import bpmn-js CSS
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

// Import properties panel CSS
import "@bpmn-io/properties-panel/dist/assets/properties-panel.css";

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
	modelName: {
		type: String,
		default: ""
	}
});

const emit = defineEmits([
	"ready",
	"changed",
	"zoom-changed",
	"launch-script-editor",
	"launch-markdown-editor",
	"launch-callactivity-editor",
	"launch-callactivity-search",
	"launch-notification-editor",
]);

// Commenting state
const comments = ref([]);
const isCommentMode = ref(false);
const showCommentDialog = ref(false);
const showViewCommentsDialog = ref(false);
const activeCommentElement = ref(null);
const selectedElementComments = ref([]);
const commentFormData = ref({
	text: "",
	assigned_to: "",
	is_task: false
});
const users = ref([]);

// Right-click context menu (composable)
const {
	showContextMenu,
	contextMenuPosition,
	contextMenuElementCommentCount,
	canAddComment,
	addCommentFromContextMenu,
	viewCommentsFromContextMenu,
	registerEventListeners: registerContextMenuListeners,
} = useBpmnContextMenu({
	readonly: computed(() => props.readonly),
	comments,
	selectCommentElement,
	openViewCommentsDialog: (elementId) => {
		selectedElementComments.value = comments.value.filter(
			(c) => c.element_id === elementId
		);
		showViewCommentsDialog.value = true;
	},
});

const userSearchQuery = ref("");
const showUserDropdown = ref(false);

// Clear assigned_to when the user edits the search text away from the selected label.
// This prevents a stale assignment if the user modifies the input after selecting someone.
watch(userSearchQuery, (newQuery) => {
	const assignedUser = commentFormData.value.assigned_to;
	if (!assignedUser) return;

	// Find the label (full_name) of the currently assigned user
	const match = users.value.find(u => u.name === assignedUser);
	if (match && newQuery !== match.full_name) {
		commentFormData.value.assigned_to = "";
	}
});

const showMentionDropdown = ref(false);
const mentionSearchQuery = ref("");
const mentionStartIndex = ref(-1);

const mentionSuggestions = computed(() => {
	const q = (mentionSearchQuery.value || "").trim().toLowerCase();
	if (!q) return [];

	return users.value
		.map(u => ({ label: u.full_name, value: u.name }))
		.filter(u => u.label.toLowerCase().includes(q) || u.value.toLowerCase().includes(q))
		.slice(0, 10);
});

const filteredUsers = computed(() => {
	const q = (userSearchQuery.value || "").toLowerCase();
	const options = users.value.map(u => ({
		label: u.full_name,
		value: u.name
	}));
	if (!q) return options;
	return options.filter(u => u.label.toLowerCase().includes(q) || u.value.toLowerCase().includes(q));
});

const container = ref(null);
const propertiesContainer = ref(null);
const toolbarEl = ref(null);
const canUndo = ref(false);
const canRedo = ref(false);
const zoomLevel = ref(100);
const showPropertiesPanel = ref(false);
const propertiesCollapsed = ref(false);
const isMounted = ref(false);
const isImporting = ref(false);
// const showMinimap = ref(true); // DISABLED
const selectedElements = shallowRef([]);
const modelerInstance = shallowRef(null);

// Mobile responsiveness
const { isMobile } = useWindowSize();
const showMobileFormatPopover = ref(false);
const dragHandleRef = ref(null);
const { dragOffset, isDragging, attach: attachBottomSheet } = useBottomSheet();

// Attach swipe-to-dismiss when the properties panel opens on mobile
watch([showPropertiesPanel, isMobile], () => {
	if (showPropertiesPanel.value && isMobile.value) {
		nextTick(() => {
			if (dragHandleRef.value) {
				attachBottomSheet(dragHandleRef.value, () => {
					showPropertiesPanel.value = false;
				});
			}
		});
	}
});

let modeler = null;
let commandStack = null;

// Empty BPMN diagram template
const emptyDiagram = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">
      <bpmndi:BPMNShape id="_BPMNShape_StartEvent_1" bpmnElement="StartEvent_1">
        <dc:Bounds x="173" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

function togglePropertiesPanel() {
	showPropertiesPanel.value = !showPropertiesPanel.value;
	// If opening the panel, ensure it's not collapsed by default
	if (showPropertiesPanel.value) {
		propertiesCollapsed.value = false;
	}
}

function togglePropertiesCollapse() {
	propertiesCollapsed.value = !propertiesCollapsed.value;
}

// toggleMinimap - DISABLED
// function toggleMinimap() {
// 	if (!modeler) return;
// 	const minimap = modeler.get("minimap");
// 	if (showMinimap.value) {
// 		minimap.close();
// 	} else {
// 		minimap.open();
// 	}
// 	showMinimap.value = !showMinimap.value;
// }

onMounted(async () => {
	isMounted.value = true;
	try {
		// Extend spiff workflow moddle definitions to include our custom timer properties
		if (spiffModdleExtension && Array.isArray(spiffModdleExtension.types)) {
			// Timer extension (hot-reloading safety)
			const hasTimerExt = spiffModdleExtension.types.find(t => t.name === "TimerEventDefinitionExtension");
			if (!hasTimerExt) {
				spiffModdleExtension.types.push({
					name: "TimerEventDefinitionExtension",
					extends: ["bpmn:TimerEventDefinition"],
					properties: [
						{ name: "cronExpression", isAttr: true, type: "String" },
						// Kept for backward compat — existing XML may contain this.
						{ name: "schedulerFrequency", isAttr: true, type: "String" }
					]
				});
			}

			// Start Event trigger extension (hot-reloading safety)
			const hasStartEventExt = spiffModdleExtension.types.find(t => t.name === "StartEventTriggerExtension");
			if (!hasStartEventExt) {
				spiffModdleExtension.types.push({
					name: "StartEventTriggerExtension",
					extends: ["bpmn:StartEvent"],
					properties: [
						{ name: "triggerDoctype",      isAttr: true, type: "String" },
						{ name: "triggerType",         isAttr: true, type: "String" },
						{ name: "triggerWorkflow",     isAttr: true, type: "String" },
						{ name: "triggerWorkflowState",isAttr: true, type: "String" }
					]
				});
			}

			// Conditional Start Event trigger extension (hot-reloading safety)
			const hasCondStartEventExt = spiffModdleExtension.types.find(t => t.name === "ConditionalEventTriggerExtension");
			if (!hasCondStartEventExt) {
				spiffModdleExtension.types.push({
					name: "ConditionalEventTriggerExtension",
					extends: ["bpmn:ConditionalEventDefinition"],
					properties: [
						{ name: "triggerDoctype",       isAttr: true, type: "String" },
						{ name: "triggerType",          isAttr: true, type: "String" },
						{ name: "triggerWorkflow",      isAttr: true, type: "String" },
						{ name: "triggerWorkflowState", isAttr: true, type: "String" }
					]
				});
			}

			// User Task assignee extension
			const hasUserTaskExt = spiffModdleExtension.types.find(t => t.name === "UserTaskAssigneeExtension");
			if (!hasUserTaskExt) {
				spiffModdleExtension.types.push({
					name: "UserTaskAssigneeExtension",
					extends: ["bpmn:UserTask"],
					properties: [
						{ name: "assigneeMode",         isAttr: true, type: "String" },
						{ name: "targetDoctype",         isAttr: true, type: "String" },
						{ name: "assigneeUser",          isAttr: true, type: "String" },
						{ name: "assigneeDocfield",      isAttr: true, type: "String" },
						{ name: "assigneeUsers",         isAttr: true, type: "String" },
						{ name: "roundRobinLastUser",    isAttr: true, type: "String" },
						{ name: "taskActions",           isAttr: true, type: "String" },
						{ name: "taskActionMode",        isAttr: true, type: "String" }
					]
				});

				spiffModdleExtension.types.push({
					name: "ScriptTaskServerScriptExtension",
					extends: ["bpmn:ScriptTask"],
					properties: [
						{ name: "serverScript", isAttr: true, type: "String" }
					]
				});
			}
			
			// Intermediate Event extension (hot-reloading safety)
			const hasIntermediateEventExt = spiffModdleExtension.types.find(t => t.name === "IntermediateEventExtension");
			if (!hasIntermediateEventExt) {
				spiffModdleExtension.types.push({
					name: "IntermediateEventExtension",
					extends: ["bpmn:IntermediateCatchEvent", "bpmn:IntermediateThrowEvent"],
					properties: [
						{ name: "targetDoctype", isAttr: true, type: "String" },
						{ name: "triggerWorkflow", isAttr: true, type: "String" },
						{ name: "triggerWorkflowState", isAttr: true, type: "String" },
						{ name: "assignmentRule", isAttr: true, type: "String" }
					]
				});
			}

			// Send Task notification extension
			const hasSendTaskExt = spiffModdleExtension.types.find(t => t.name === "SendTaskNotificationExtension");
			if (!hasSendTaskExt) {
				spiffModdleExtension.types.push({
					name: "SendTaskNotificationExtension",
					extends: ["bpmn:SendTask"],
					properties: [
						{ name: "notificationName", isAttr: true, type: "String" }
					]
				});
			}

			// Service Task "Apply Workflow" extension
			const hasServiceTaskExt = spiffModdleExtension.types.find(t => t.name === "ServiceTaskApplyWorkflowExtension");
			if (!hasServiceTaskExt) {
				spiffModdleExtension.types.push({
					name: "ServiceTaskApplyWorkflowExtension",
					extends: ["bpmn:ServiceTask"],
					properties: [
						{ name: "serviceType",          isAttr: true, type: "String" },
						{ name: "serviceTargetDoctype", isAttr: true, type: "String" },
						{ name: "workflowState",        isAttr: true, type: "String" },
						{ name: "docStatus",            isAttr: true, type: "String" },
						{ name: "onlyAllowEdit",        isAttr: true, type: "String" },
						{ name: "confirmTransition",    isAttr: true, type: "String" },
						{ name: "emailAccount",         isAttr: true, type: "String" },
						{ name: "emailUseDoctype",      isAttr: true, type: "String" },
						{ name: "emailDoctype",         isAttr: true, type: "String" },
						{ name: "emailSubject",         isAttr: true, type: "String" },
						{ name: "emailTo",              isAttr: true, type: "String" },
						{ name: "emailToDocFields",     isAttr: true, type: "String" },
						{ name: "emailToRoles",         isAttr: true, type: "String" },
						{ name: "emailCc",              isAttr: true, type: "String" },
						{ name: "emailBcc",             isAttr: true, type: "String" },
						{ name: "emailBody",            isAttr: true, type: "String" },
						{ name: "updateFieldDoctype",   isAttr: true, type: "String" },
						{ name: "updateFieldName",      isAttr: true, type: "String" },
						{ name: "updateFieldValue",     isAttr: true, type: "String" }
					]
				});
			}

			// Sticky Note extension
			const hasStickyNoteExt = spiffModdleExtension.types.find(t => t.name === "StickyNoteExtension");
			if (!hasStickyNoteExt) {
				spiffModdleExtension.types.push({
					name: "StickyNoteExtension",
					extends: ["bpmn:TextAnnotation"],
					properties: [
						{ name: "isStickyNote", isAttr: true, type: "Boolean" },
						{ name: "color", isAttr: true, type: "String" }
					]
				});
			}
		}

				
	await initModeler({
		container,
		propertiesContainer,
		modelerConfig: {
			additionalModules: [
				BpmnPropertiesPanelModule,
				BpmnPropertiesProviderModule,
				spiffworkflow,
				userTaskPropertiesProviderModule,
				sendTaskPropertiesProviderModule,
				serviceTaskPropertiesProviderModule,
				scriptTaskPropertiesProviderModule,
				intermediateEventPropertiesProviderModule,
				timerPropertiesProviderModule,
				startEventPropertiesProviderModule,
				conditionalStartEventPropertiesProviderModule,
				// minimapModule, // DISABLED
				translateModule,
				customTextStyleModule,
				resizeModule,
				stickyNoteModule,
				clipboardModule,
				lintModule,
				nativeCopyPasteModule,
			],
			taskResizingEnabled: true,
			linting: {
				active: true,
				bpmnlint: bpmnlintConfig,
			},
			moddleExtensions: {
				custom: customTextStyleModdle,
				spiffworkflow: spiffModdleExtension,
			},
			bpmnRenderer: {
				defaultFillColor: "#ffffff",
				defaultStrokeColor: "#1f2937",
			},
			textRenderer: {
				defaultStyle: {
					fontFamily: '"Inter", "Segoe UI", system-ui, sans-serif',
					fontSize: "12px",
				},
			},
			// Disable keyboard bindings in readonly mode
			keyboard: props.readonly ? false : { bindTo: document },
		},
		onReady: async (initializedModeler) => {
			modeler = initializedModeler;
			modelerInstance.value = modeler;

			// Fetch users for assignment
			fetchUsers();

			// Initial fetch of comments
			if (props.modelName) {
				fetchComments();
			}

			// Get command stack for undo/redo
			commandStack = modeler.get("commandStack");

			// Use eventBus for listening to command stack changes
			const eventBus = modeler.get("eventBus");


			const linting = modeler.get("linting");
			if (linting) {
				const originalFormatIssues = linting._formatIssues;
				linting._formatIssues = function (issues) {
					let formattedIssues = originalFormatIssues.call(this, issues);
					const canvas = modeler.get("canvas");
					const rootElement = canvas.getRootElement();

					// Helper to collect all element IDs strictly contained within the given moddle object
					const getModdleDescendants = (bo, descendants = new Set(), visited = new Set()) => {
						if (!bo || typeof bo !== "object") return descendants;
						if (visited.has(bo)) return descendants;
						visited.add(bo);

						if (bo.id) descendants.add(bo.id);

						const containmentKeys = [
							"flowElements", "laneSets", "artifacts", "eventDefinitions",
							"participants", "messageFlows", "processRef", "rootElements"
						];

						for (const key of containmentKeys) {
							const val = bo[key];
							if (Array.isArray(val)) {
								val.forEach(child => getModdleDescendants(child, descendants, visited));
							} else if (val && typeof val === "object") {
								getModdleDescendants(val, descendants, visited);
							}
						}
						return descendants;
					};

					const validIds = getModdleDescendants(rootElement.businessObject);

					for (const elementId in formattedIssues) {
						const issueGroup = formattedIssues[elementId];
						// Filter reports to ensure their actual element is a descendant
						const filteredGroup = issueGroup.filter(report => {
							const actualId = report.actualElementId || report.id;
							return validIds.has(actualId);
						});

						if (filteredGroup.length === 0) {
							delete formattedIssues[elementId];
						} else {
							formattedIssues[elementId] = filteredGroup;
						}
					}

					return formattedIssues;
				};

				// Rerun linting when drilling down/up so the panel stays relevant to current plane
				eventBus.on("root.set", () => {
					linting.update();
				});
			}

			// Clear custom trigger attributes if a StartEvent is converted into something else
			// (e.g. Timer Start Event) so they don't persist in the XML.
			// Use modeling.updateModdleProperties so the operation is tracked by the command
			// stack and is properly undoable/redoable.
			eventBus.on("commandStack.shape.replace.postExecute", (e) => {
				const newShape = e.context.newShape;
				const bo = newShape && newShape.businessObject;
				if (!bo) return;

				const modeling = modeler.get("modeling");
				const triggerAttrs = ["triggerDoctype", "triggerType", "triggerWorkflow", "triggerWorkflowState"];
				const clearProps = {};
				triggerAttrs.forEach(attr => {
					clearProps[`spiffworkflow:${attr}`] = undefined;
				});

				if (bo.$type === "bpmn:StartEvent") {
					const eventDefs = bo.get("eventDefinitions") || [];
					const isPlainStartEvent = eventDefs.length === 0;
					const hasConditionalDef = eventDefs.some(d => d.$type === "bpmn:ConditionalEventDefinition");

					// Clear trigger attrs from the StartEvent BO if it's no longer plain
					if (!isPlainStartEvent) {
						modeling.updateModdleProperties(newShape, bo, clearProps);
					}

					// Clear trigger attrs from ConditionalEventDefinition if the shape
					// was converted away from a Conditional Start Event
					if (!hasConditionalDef) {
						// Check the old shape's event defs for stale conditional data
						const oldShape = e.context.oldShape;
						const oldBo = oldShape && oldShape.businessObject;
						if (oldBo) {
							const oldDefs = oldBo.get("eventDefinitions") || [];
							const oldCondDef = oldDefs.find(d => d.$type === "bpmn:ConditionalEventDefinition");
							if (oldCondDef) {
								modeling.updateModdleProperties(newShape, oldCondDef, clearProps);
							}
						}
					}
				} else {
					// Not a StartEvent at all — clear any lingering trigger attrs
					modeling.updateModdleProperties(newShape, bo, clearProps);
				}
			});


			// Listen for selection changes for formatting toolbar
			eventBus.on("selection.changed", (e) => {
				selectedElements.value = e.newSelection || [];

				// Inject Process Name field when a Call Activity is selected
				const single = e.newSelection?.length === 1 ? e.newSelection[0] : null;
				if (single?.type === "bpmn:CallActivity") {
					injectProcessNameField(single, propertiesContainer);
				} else {
					// Cancel any in-flight resolve before removing the field
					cancelPendingInjection();
					removeProcessNameField(propertiesContainer);
				}
			});

			// Canvas/Element click listener for commenting
			const handleCommentClick = (element, originalEvent) => {
				if (!isCommentMode.value || !element) return;

				// Guard against missing originalEvent
				if (originalEvent) {
					originalEvent.preventDefault();
					originalEvent.stopPropagation();
				}

				selectCommentElement(element);
				return false;
			};

			eventBus.on("element.click", (e) => {
				return handleCommentClick(e.element, e.originalEvent);
			});

			eventBus.on("canvas.click", (e) => {
				const canvas = modeler.get("canvas");
				return handleCommentClick(canvas?.getRootElement(), e.originalEvent);
			});

			// Right-click context menu — delegates to composable
			registerContextMenuListeners(eventBus);

			// Re-inject only when calledElement actually changed
			// churn and repeated network requests on every command stack event.
			eventBus.on("commandStack.changed", () => {
				updateUndoRedoState();
				const selection = modeler.get("selection");
				const selected = selection.get();
				if (selected?.length === 1 && selected[0]?.type === "bpmn:CallActivity") {
					reinjectIfCalledElementChanged(selected[0], propertiesContainer);
				}
			});

		// Listen for zoom changes (Ctrl+scroll, programmatic zoom, etc.)
		eventBus.on("canvas.viewbox.changed", () => {
			const canvas = modeler.get("canvas");
			const newZoom = Math.round(canvas.zoom() * 100);
			zoomLevel.value = newZoom;
			emit("zoom-changed", newZoom);
		});

		// Ensure comments are rendered after any diagram import finishes
		eventBus.on("import.done", () => {
			renderComments();
		});

		// --- SpiffWorkflow EventBus Integration ---
		// These handlers are required for the spiffworkflow properties panel
		// "Launch Editor" buttons and data-request dropdowns to function.

		// Script editing (Script Tasks, Pre/Post scripts)
		eventBus.on("spiff.script.edit", (event) => {
			emit("launch-script-editor", {
				element: event.element,
				scriptType: event.scriptType,
				script: event.script || "",
				eventBus: event.eventBus,
			});
		});

			eventBus.on("spiff.markdown.edit", (event) => {
				emit("launch-markdown-editor", {
					element: event.element,
					value: event.value || "",
					eventBus: event.eventBus,
				});
			});

			eventBus.on("spiff.callactivity.edit", (event) => {
				emit("launch-callactivity-editor", {
					processId: event.processId,
					element: event.element,
				});
			});

			eventBus.on("spiff.callactivity.search", (event) => {
				emit("launch-callactivity-search", {
					processId: event.processId,
					eventBus: event.eventBus,
					element: event.element,
				});
			});

			eventBus.on("spiff.file.edit", (_event) => {
				// Not implemented — file editing is handled externally
			});

			eventBus.on("spiff.dmn.edit", (_event) => {
				// Not implemented — DMN editing is handled externally
			});

			// Notification editing (Send Tasks)
			eventBus.on("spiff.notification.edit", (event) => {
				emit("launch-notification-editor", {
					element: event.element,
					notificationName: event.notificationName || "",
					eventBus: event.eventBus,
				});
			});

			// Write notification name back to BPMN element when dialog resolves
			eventBus.on("spiff.notification.update", (event) => {
				if (event.element && event.notificationName) {
					const modeling = modeler.get("modeling");
					const bo = event.element.businessObject || event.element;
					modeling.updateModdleProperties(event.element, bo, {
						"spiffworkflow:notificationName": event.notificationName,
					});
				}
			});

			eventBus.on("spiff.service_tasks.requested", (event) => {
				event.eventBus.fire("spiff.service_tasks.returned", {
					serviceTaskOperators: [],
				});
			});

			eventBus.on("spiff.json_schema_files.requested", (event) => {
				event.eventBus.fire("spiff.json_schema_files.returned", {
					options: [],
				});
			});

			eventBus.on("spiff.dmn_files.requested", (event) => {
				event.eventBus.fire("spiff.dmn_files.returned", {
					options: [],
				});
			});

			// nativeCopyPasteModule fires 'native-copy-paste:error' on any
			// clipboard API failure (unavailable, permission denied, or parse
			// error). Log it here so it surfaces in the browser console.
			eventBus.on("native-copy-paste:error", ({ message, error }) => {
				console.warn("[native-copy-paste]", message, error);
			});


			eventBus.on("spiff.data_stores.requested", (event) => {
				event.eventBus.fire("spiff.data_stores.returned", {
					options: [],
				});
			});

			eventBus.on("spiff.messages.requested", (event) => {
				event.eventBus.fire("spiff.messages.returned", {
					configuration: { messages: [] },
				});
			});

			eventBus.on("spiff.msg_json_schema_files.requested", (event) => {
				event.eventBus.fire("spiff.msg_json_schema_files.returned", { options: [] });
			});

			// Fix unresolved loop data references (from upstream app.js)
			modeler.on("import.parse.complete", (event) => {
				const refs = (event.references || []).filter(
					(r) =>
						r.property === "bpmn:loopDataInputRef" ||
						r.property === "bpmn:loopDataOutputRef"
				);
				const desc = modeler._moddle.registry.getEffectiveDescriptor(
					"bpmn:ItemAwareElement"
				);
				refs.forEach((ref) => {
					const props = {
						id: ref.id,
						name: ref.id ? typeof ref.name === "undefined" : ref.name,
					};
					const elem = modeler._moddle.create(desc, props);
					elem.$parent = ref.element;
					ref.element.set(ref.property, elem);
				});
			});

			// Expose modeler instance for child components
			modelerInstance.value = modeler;

			// Import empty diagram
			await modeler.importXML(emptyDiagram);

			// Append toolbar natively to top header
			isMounted.value = true;
			const targetToolbar = document.getElementById("bpmn-editor-toolbar");
			if (targetToolbar && toolbarEl.value) {
				targetToolbar.innerHTML = '';
				targetToolbar.appendChild(toolbarEl.value);
			}



			// In readonly mode, disable all modeler-level editing interactions
			// so users cannot move, delete, or modify elements locally.
			if (props.readonly) {
				// Intercept commandStack to prevent any model mutations
				const originalExecute = commandStack.execute.bind(commandStack);
				commandStack.execute = (command, context) => {
					// Allow canvas operations (zoom, scroll) but block element mutations
					const allowedCommands = ['canvas.updateRootElement'];
					if (allowedCommands.includes(command)) {
						return originalExecute(command, context);
					}
					// Silently ignore all other commands
					return;
				};

				// Disable direct editing (double-click labels)
				try {
					const directEditing = modeler.get('directEditing');
					if (directEditing) {
						directEditing.cancel();
						const origActivate = directEditing.activate;
						directEditing.activate = () => false;
					}
				} catch (_) { /* module may not exist */ }

				// Disable dragging
				try {
					const dragging = modeler.get('dragging');
					if (dragging) {
						const origInit = dragging.init;
						dragging.init = () => {};
					}
				} catch (_) { /* module may not exist */ }
			}

			emit("ready");
		},
		onError: (err) => {
			console.error("Failed to initialize BPMN modeler:", err);
		},
		
	});
	} catch (err) {
		console.error("Error in onMounted initialized setup:", err);
	}
});

onBeforeUnmount(() => {
	isMounted.value = false;
	// Safely clean up native DOM mounting
	if (toolbarEl.value && toolbarEl.value.parentNode) {
		toolbarEl.value.parentNode.removeChild(toolbarEl.value);
	}
	// Cancel any pending process-name injection to prevent memory-leaks
	// and stale DOM updates after the component is torn down.
	cancelPendingInjection();
	if (modeler) {
		modeler.destroy();
	}
});

function updateUndoRedoState() {
	if (commandStack) {
		canUndo.value = commandStack.canUndo();
		canRedo.value = commandStack.canRedo();
	}
	// Suppress change events in readonly mode so auto-save doesn't fire
	if (!isImporting.value && !props.readonly) {
		emit("changed");
	}
}

function undo() {
	if (commandStack && commandStack.canUndo()) {
		commandStack.undo();
	}
}

function redo() {
	if (commandStack && commandStack.canRedo()) {
		commandStack.redo();
	}
}

function deleteSelected() {
	if (!modeler) return;

	const selection = modeler.get("selection");
	const modeling = modeler.get("modeling");
	const selected = selection.get();

	if (selected && selected.length > 0) {
		modeling.removeElements(selected);
	}
}

function addStickyNote() {
	if (!modeler) return;

	const modeling = modeler.get("modeling");
	const canvas = modeler.get("canvas");
	const bpmnFactory = modeler.get("bpmnFactory");
	const elementFactory = modeler.get("elementFactory");

	const rootElement = canvas.getRootElement();

	// Create TextAnnotation business object
	const textAnnotationBo = bpmnFactory.create("bpmn:TextAnnotation", {
		text: "New Note",
	});

	// Set the custom attribute within the spiffworkflow namespace
	textAnnotationBo.set("spiffworkflow:isStickyNote", true);
	textAnnotationBo.set("spiffworkflow:color", "#fff9c4"); // Default pastel yellow

	// Get viewport center
	const viewbox = canvas.viewbox();
	const x = viewbox.x + viewbox.width / 2;
	const y = viewbox.y + viewbox.height / 2;

	const shape = elementFactory.createShape({
		type: "bpmn:TextAnnotation",
		businessObject: textAnnotationBo,
		width: 150,
		height: 120,
	});

	modeling.createShape(shape, { x, y }, rootElement);
	
	// Select the new shape and activate direct editing
	const selection = modeler.get("selection");
	selection.select(shape);
	
	const directEditing = modeler.get("directEditing");
	// Small delay to ensure the SVG is rendered before activating editor
	setTimeout(() => {
		if (directEditing.canActivate(shape)) {
			directEditing.activate(shape);
		}
	}, 100);
}

// --- Commenting Methods ---

function toggleCommentMode() {
	if (!isCommentMode.value) {
		// If an element is already selected, open the dialog immediately for it
		const selection = modeler?.get("selection");
		const selected = selection?.get();
		if (selected && selected.length === 1) {
			selectCommentElement(selected[0]);
			return; // Don't enter mode if we immediately opened the dialog
		}
		isCommentMode.value = true;
	} else {
		isCommentMode.value = false;
		activeCommentElement.value = null;
		showCommentDialog.value = false;
	}
}

function selectCommentElement(element) {
	activeCommentElement.value = element;
	commentFormData.value = {
		text: "",
		assigned_to: "",
		is_task: false
	};
	userSearchQuery.value = "";
	showUserDropdown.value = false;
	showCommentDialog.value = true;
	showMentionDropdown.value = false;
}

function handleCommentInput(e) {
	if (!e || !e.target || typeof e.target.selectionStart !== 'number') return;
	
	const text = commentFormData.value.text || "";
	const cursorPosition = e.target.selectionStart;
	
	// Check text leading up to cursor for an active mention
	const textBeforeCursor = text.substring(0, cursorPosition);
	// Match `@` followed by any non-whitespace characters until the end
	const match = textBeforeCursor.match(/@([^\s]{0,30})$/);
	
	if (match) {
		showMentionDropdown.value = true;
		mentionSearchQuery.value = match[1];
		mentionStartIndex.value = cursorPosition - match[0].length;
	} else {
		showMentionDropdown.value = false;
	}
}

function selectMention(user) {
	const text = commentFormData.value.text || "";
	// Insert "@First Last " replacing the "@SearchTerm"
	const before = text.substring(0, mentionStartIndex.value);
	const after = text.substring(mentionStartIndex.value + mentionSearchQuery.value.length + 1);
	
	commentFormData.value.text = before + '@' + user.label + ' ' + after;
	showMentionDropdown.value = false;
}

async function fetchUsers() {
	if (users.value.length > 0) return; // Already fetched
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_system_users",
		});
		users.value = (response.message || response || []).filter(u => u.full_name);
	} catch (err) {
		console.error("Failed to fetch users:", err);
	}
}

async function fetchComments() {
	if (!props.modelName) return;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_canvas_comments",
			params: { model_name: props.modelName }
		});
		comments.value = response.message || response || [];
		renderComments();
	} catch (err) {
		console.error("Failed to fetch comments:", err);
	}
}

function renderComments() {
	if (!modeler) return;
	const overlays = modeler.get("overlays");
	
	// Clear existing overlays of type 'processa-comment'
	overlays.remove({ type: "processa-comment" });

	// Group comments by element_id
	const grouped = comments.value.reduce((acc, c) => {
		const id = c.element_id || "process";
		if (!acc[id]) acc[id] = [];
		acc[id].push(c);
		return acc;
	}, {});

	Object.keys(grouped).forEach(elementId => {
		const elementComments = grouped[elementId];
		const hasOpenTask = elementComments.some(c => c.is_task && c.status === "Open");
		
		// Create overlay HTML
		const html = document.createElement("div");
		html.className = `p-1 rounded-full shadow-md cursor-pointer border border-white transition-transform hover:scale-110 ${hasOpenTask ? 'bg-orange-500 text-white' : 'bg-blue-500 text-white'}`;
		html.style.width = "20px";
		html.style.height = "20px";
		html.style.display = "flex";
		html.style.alignItems = "center";
		html.style.justifyContent = "center";
		html.title = `${elementComments.length} comment(s)`;
		
		const icon = document.createElement("span");
		icon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
		html.appendChild(icon);

		html.onclick = (e) => {
			e.stopPropagation();
			selectedElementComments.value = elementComments;
			showViewCommentsDialog.value = true;
		};

		const elementRegistry = modeler.get("elementRegistry");
		const targetElement = elementRegistry.get(elementId);
		
		if (!targetElement) {
			console.warn(`Element ${elementId} not found in registry, skipping comment overlay`);
			return;
		}

		try {
			overlays.add(elementId, "processa-comment", {
				position: {
					top: -10,
					left: -10
				},
				html: html
			});
		} catch (err) {
			console.error(`Failed to add overlay for element ${elementId}:`, err);
		}
	});
}

async function submitComment() {
	if (!commentFormData.value.text || !props.modelName) return;

	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.post_canvas_comment",
			params: {
				model_name: props.modelName,
				element_id: activeCommentElement.value?.id || "process",
				comment: commentFormData.value.text,
				assigned_to: commentFormData.value.assigned_to,
				is_task: commentFormData.value.is_task ? 1 : 0
			}
		});

		showCommentDialog.value = false;
		isCommentMode.value = false;
		fetchComments();
	} catch (err) {
		console.error("Failed to post comment:", err);
	}
}

async function resolveComment(comment) {
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.update_comment_status",
			params: {
				name: comment.name,
				status: "Resolved"
			}
		});
		fetchComments();
		// Update the local list if dialog is open
		const idx = selectedElementComments.value.findIndex(c => c.name === comment.name);
		if (idx > -1) {
			selectedElementComments.value[idx].status = "Resolved";
		}
	} catch (err) {
		console.error("Failed to resolve comment:", err);
	}
}

// Watch for model name changes to refetch comments
watch(() => props.modelName, (newVal) => {
	if (newVal) {
		fetchComments();
	}
});

// --- End Commenting Methods ---

// Decode HTML entities
function decodeHtmlEntities(text) {
	const textarea = document.createElement("textarea");
	textarea.innerHTML = text;
	return textarea.value;
}

// Expose methods for parent component
async function getXML() {
	if (!modeler) return "";
	const { xml } = await modeler.saveXML({ format: true });
	return xml;
}

async function loadXML(xml) {
	if (!modeler) return;
	isImporting.value = true;
	try {
		// Decode any HTML entities in the XML
		const decodedXml = decodeHtmlEntities(xml);
		await modeler.importXML(decodedXml);
		updateUndoRedoState();
		renderComments();
		// Fit diagram to screen by default after loading, safely catching zero-dimension errors
		setTimeout(() => {
			try {
				const canvas = modeler.get("canvas");
				canvas.zoom("fit-viewport");
				zoomLevel.value = Math.round(canvas.zoom() * 100);
			} catch (e) {
				console.warn("Could not fit viewport automatically - container may be hidden:", e);
			}
		}, 100);
	} catch (err) {
		console.error("Failed to import XML:", err);
	} finally {
		isImporting.value = false;
	}
}

function zoomIn() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	const currentZoom = canvas.zoom();
	const newZoom = Math.min(currentZoom * 1.1, 4); // Max 400%
	canvas.zoom(newZoom);
	zoomLevel.value = Math.round(newZoom * 100);
}

function zoomOut() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	const currentZoom = canvas.zoom();
	const newZoom = Math.max(currentZoom / 1.1, 0.1); // Min 10%
	canvas.zoom(newZoom);
	zoomLevel.value = Math.round(newZoom * 100);
}

function resetZoom() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	canvas.zoom(1);
	zoomLevel.value = 100;
}

function fitToScreen() {
	if (!modeler) return;
	const canvas = modeler.get("canvas");
	canvas.zoom("fit-viewport");
	zoomLevel.value = Math.round(canvas.zoom() * 100);
}

function getZoomLevel() {
	return zoomLevel.value;
}

// Handle drag over for custom shapes
function handleDragOver(event) {
	event.dataTransfer.dropEffect = "copy";
}

// Handle drop of custom shape onto canvas
function handleDrop(event) {
	const dataStr = event.dataTransfer.getData("application/json");
	if (!dataStr) return;

	try {
		const shapeData = JSON.parse(dataStr);
		if (shapeData && shapeData.svg_content) {
			// Get drop position relative to canvas
			const canvas = modeler.get("canvas");
			const viewbox = canvas.viewbox();
			const containerRect = container.value.getBoundingClientRect();

			// Calculate position in diagram coordinates
			const x = viewbox.x + (event.clientX - containerRect.left) / viewbox.scale;
			const y = viewbox.y + (event.clientY - containerRect.top) / viewbox.scale;

			addCustomShape(shapeData.svg_content, x, y, shapeData.shape_name);
		}
	} catch (e) {
		console.error("Failed to parse dropped shape data:", e);
	}
}

// Add a custom shape at the specified position
function addCustomShape(svgContent, x, y, name = "Custom Shape") {
	if (!modeler) return;

	const modeling = modeler.get("modeling");
	const elementFactory = modeler.get("elementFactory");
	const canvas = modeler.get("canvas");
	const bpmnFactory = modeler.get("bpmnFactory");

	// Get the root element (process)
	const rootElement = canvas.getRootElement();

	// Create a Task business object
	const taskBo = bpmnFactory.create("bpmn:Task", {
		name: name,
	});

	// Create the shape element
	const shape = elementFactory.createShape({
		type: "bpmn:Task",
		businessObject: taskBo,
		width: 100,
		height: 80,
	});

	// Store SVG content in the global map BEFORE adding to canvas
	customShapeSvgStore.set(shape.id, svgContent);

	// Add to canvas (this triggers the renderer)
	modeling.createShape(shape, { x, y }, rootElement);
}

// Overlay API functions
function getOverlays() {
	if (!modeler) return null;
	return modeler.get("overlays");
}

function addOverlay(elementId, html, options = {}) {
	const overlays = getOverlays();
	if (!overlays) return null;
	
	const defaultOptions = {
		position: { top: -30, left: 0 },
		...options,
	};
	
	return overlays.add(elementId, {
		position: defaultOptions.position,
		html,
	});
}

function removeOverlay(overlayId) {
	const overlays = getOverlays();
	if (overlays && overlayId) {
		overlays.remove(overlayId);
	}
}

function removeOverlaysByElement(elementId) {
	const overlays = getOverlays();
	if (overlays && elementId) {
		overlays.remove({ element: elementId });
	}
}

function clearAllOverlays() {
	const overlays = getOverlays();
	if (overlays) {
		overlays.clear();
	}
}

// Element Color API functions
function setElementColor(elementIds, stroke, fill) {
	if (!modeler) return;
	const modeling = modeler.get("modeling");
	const elementRegistry = modeler.get("elementRegistry");
	
	const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
	const elements = ids.map(id => elementRegistry.get(id)).filter(Boolean);
	
	if (elements.length > 0) {
		modeling.setColor(elements, { stroke, fill });
	}
}

function clearElementColor(elementIds) {
	if (!modeler) return;
	const modeling = modeler.get("modeling");
	const elementRegistry = modeler.get("elementRegistry");
	
	const ids = Array.isArray(elementIds) ? elementIds : [elementIds];
	const elements = ids.map(id => elementRegistry.get(id)).filter(Boolean);
	
	if (elements.length > 0) {
		modeling.setColor(elements, null);
	}
}

function getSelectedElements() {
	if (!modeler) return [];
	const selection = modeler.get("selection");
	return selection.get();
}


// Directly update calledElement on a Call Activity via the command stack.
// This is the reliable way to update the property regardless of SpiffWorkflow's
// async once-listener state.
function updateCalledElement(element, processId) {
	if (!modeler || !element) return;
	const cmdStack = modeler.get("commandStack");
	cmdStack.execute("element.updateProperties", {
		element,
		moddleElement: element.businessObject,
		properties: { calledElement: processId },
	});
	// Force the properties panel to re-initialize (and re-read getValue)
	// by cycling the selection. Without this the Preact TextFieldEntry
	// shows stale data until the page is refreshed.
	const selection = modeler.get("selection");
	selection.select(null);
	setTimeout(() => {
		selection.select(element);
	}, 30);
}

defineExpose({
	getXML,
	loadXML,
	undo,
	redo,
	deleteSelected,
	addStickyNote,
	zoomIn,
	zoomOut,
	resetZoom,
	fitToScreen,
	getZoomLevel,
	addCustomShape,
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
	togglePropertiesPanel,
	togglePropertiesCollapse,
});
</script>

<style>
.bpmn-editor-wrapper {
	background: #fff;
}

.bpmn-canvas {
	background: #fafafa;
}

.bpmn-canvas.comment-mode-active .djs-container {
	cursor: crosshair !important;
}

/* ── Injected Process Name field (no inline styles) ─── */
.bpmn-process-name-value {
	display: flex;
	align-items: center;
	min-height: 28px;
	padding: 2px 8px;
	font-size: 12px;
	color: var(--gray-900, #111827);
	background: var(--gray-50, #f9fafb);
	border: 1px solid var(--gray-200, #e5e7eb);
	border-radius: 4px;
	word-break: break-word;
}

.bpmn-process-name-resolving {
	color: var(--gray-400, #9ca3af);
	font-style: italic;
}

.bpmn-process-name-empty {
	color: var(--gray-400, #9ca3af);
	font-style: italic;
}
/* ─────────────────────────────────────────────────── */

/* Launch Editor Button Styling */
.properties-panel-container .spiffworkflow-properties-panel-button {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 6px 14px;
	margin: 4px 8px 8px;
	font-size: 12px;
	font-weight: 500;
	color: #374151;
	background: #f3f4f6;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	cursor: pointer;
	transition: all 0.15s ease;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.properties-panel-container .spiffworkflow-properties-panel-button:hover {
	background: #e5e7eb;
	border-color: #9ca3af;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.properties-panel-container .spiffworkflow-properties-panel-button:active {
	background: #d1d5db;
	box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* Palette Styling */
.bpmn-canvas .djs-palette {
	background: #f8f9fa;
	border-right: 1px solid #e5e7eb;
	border-radius: 0;
}

.bpmn-canvas .djs-palette .entry:hover {
	background: #e5e7eb;
}

.bpmn-canvas .djs-palette .separator {
	border-top-color: #e5e7eb;
}

/* Element Selection Styling */
.djs-element.selected .djs-outline {
	stroke: #3b82f6 !important;
	stroke-width: 2px !important;
}

.djs-element.hover .djs-outline {
	stroke: #60a5fa !important;
	stroke-width: 1.5px !important;
}

/* Context Pad Styling */
.djs-context-pad .entry:hover {
	background: #3b82f6 !important;
}

.djs-context-pad .entry:hover svg {
	fill: white;
}

/* Contain BPMN z-index values within the canvas stacking context.
   Without this, context pad (z-index:100) and popup menu (z-index:200)
   bleed through frappe-ui Dialog overlays. */
.bpmn-canvas {
	isolation: isolate;
}

/* Canvas Focus */
.bpmn-canvas:focus {
	outline: none;
}

/* Properties Panel Styling (Frappe UI Skin) */
.properties-panel-container {
	--properties-panel-header-background-color: #f9fafb;
	--properties-panel-group-header-background-color: #f3f4f6;
	font-family: 'Inter', system-ui, sans-serif;
	isolation: isolate;
}

.properties-panel-container .bio-properties-panel {
	height: 100%;
}

.properties-panel-container .bio-properties-panel-header {
	background-color: #f9fafb;
	border-bottom: 1px solid #e5e7eb;
	padding: 12px 16px;
}

.properties-panel-container .bio-properties-panel-header-title {
	font-size: 14px;
	font-weight: 700;
	color: #1f2937;
}

.properties-panel-container .bio-properties-panel-group-header {
	background-color: #f3f4f6;
	border-bottom: 1px solid #e5e7eb;
	padding: 8px 16px;
	transition: background-color 0.2s ease;
}

.properties-panel-container .bio-properties-panel-group-header:hover {
	background-color: #e5e7eb;
}

.properties-panel-container .bio-properties-panel-group-header-title {
	font-size: 11px;
	font-weight: 700;
	color: #4b5563;
	text-transform: uppercase;
	letter-spacing: 0.05em;
}

/* Form Controls */
.properties-panel-container .bio-properties-panel-label {
	display: block;
	font-size: 12px;
	font-weight: 500;
	color: #4b5563;
	margin-bottom: 6px;
	margin-top: 12px;
}

.properties-panel-container .bio-properties-panel-input,
.properties-panel-container .bio-properties-panel-select,
.properties-panel-container .bio-properties-panel-textarea {
	width: 100%;
	background-color: #f9fafb;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	padding: 6px 10px;
	font-size: 13px;
	color: #1f2937;
	transition: all 0.2s ease;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.properties-panel-container .bio-properties-panel-input:focus,
.properties-panel-container .bio-properties-panel-select:focus,
.properties-panel-container .bio-properties-panel-textarea:focus {
	outline: none;
	background-color: #ffffff;
	border-color: #3b82f6;
	box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.properties-panel-container .bio-properties-panel-input::placeholder {
	color: #9ca3af;
}

/* Checkbox Styling */
.properties-panel-container .bio-properties-panel-checkbox {
	width: 16px;
	height: 16px;
	border-radius: 4px;
	border: 1px solid #d1d5db;
	cursor: pointer;
}

/* Group Entries */
.properties-panel-container .bio-properties-panel-entry {
	padding: 8px 16px;
}

.properties-panel-container .bio-properties-panel-group-entries {
	border-bottom: 1px solid #f3f4f6;
	padding-bottom: 8px;
}

/* Frequency Explanation Card (Timer Start Event) */
.properties-panel-container .frequency-explanation {
	padding: 6px 10px;
}

.properties-panel-container .frequency-explanation__card {
	background: var(--properties-panel-group-header-background-color, #f3f4f6);
	border-radius: 6px;
	padding: 12px;
	font-size: 12.5px;
	line-height: 1.6;
	color: #374151;
}

.properties-panel-container .frequency-explanation__title {
	font-weight: 600;
	font-size: 13px;
	margin-bottom: 8px;
	color: #111827;
}

.properties-panel-container .frequency-explanation__desc {
	margin-bottom: 8px;
}

.properties-panel-container .frequency-explanation__label {
	font-weight: 600;
	color: #111827;
}

.properties-panel-container .frequency-explanation__note {
	font-size: 11.5px;
	color: #6b7280;
	font-style: italic;
}

/* Minimap Styling */
.djs-minimap {
	background: #ffffff;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
	box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
}

.djs-minimap .map {
	border-radius: 6px;
}

.djs-minimap .viewport {
	border: 2px solid #3b82f6;
	background: rgba(59, 130, 246, 0.1);
}

/* Overlay Styling */
.bpmn-overlay {
	padding: 4px 8px;
	border-radius: 4px;
	font-size: 12px;
	font-weight: 500;
	white-space: nowrap;
	pointer-events: auto;
	cursor: pointer;
}

.bpmn-overlay-error {
	background: #ef4444;
	color: white;
}

.bpmn-overlay-warning {
	background: #f59e0b;
	color: white;
}

.bpmn-overlay-info {
	background: #3b82f6;
	color: white;
}

.bpmn-overlay-success {
	background: #10b981;
	color: white;
}

.bpmn-overlay-badge {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: 20px;
	height: 20px;
	border-radius: 10px;
	font-size: 11px;
	font-weight: 600;
}

/* ── Breadcrumb Navigation (collapsed subprocess drilldown) ── */
.bpmn-canvas .bjs-breadcrumbs {
	font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
	font-size: 14px;
	z-index: 10;
}

.bpmn-canvas .bjs-breadcrumbs li a {
	color: #3b82f6;
	text-decoration: none;
	transition: color 0.15s ease;
}

.bpmn-canvas .bjs-breadcrumbs li a:hover {
	color: #2563eb;
	text-decoration: underline;
}

.bpmn-canvas .bjs-breadcrumbs li:last-of-type a {
	color: #374151;
	font-weight: 500;
}

/* ── Read-Only Mode ─────────────────────────────── */

/* Hide palette and context pad in read-only mode */
.bpmn-canvas--readonly .djs-palette,
.bpmn-canvas--readonly .djs-context-pad,
.bpmn-canvas--readonly .djs-popup,
.bpmn-canvas--readonly .djs-direct-editing-parent {
	display: none !important;
}

/* Disable drag/move cursor on elements in read-only mode */
.bpmn-canvas--readonly .djs-element {
	cursor: default !important;
}

/* Semi-transparent overlay to visually indicate read-only */
.bpmn-canvas--readonly {
	position: relative;
}

.bpmn-canvas--readonly::after {
	content: '';
	position: absolute;
	inset: 0;
	background: rgba(248, 250, 252, 0.15);
	pointer-events: none;
	z-index: 1;
}

/* Make properties panel inputs read-only */
.properties-panel--readonly input,
.properties-panel--readonly textarea,
.properties-panel--readonly select,
.properties-panel--readonly button {
	pointer-events: none !important;
	opacity: 0.7;
}

/* But keep the panel header and group headers interactive for collapsing */
.properties-panel--readonly .bio-properties-panel-group-header {
	pointer-events: auto !important;
	opacity: 1;
}

.properties-panel--readonly .bio-properties-panel-header {
	pointer-events: auto !important;
	opacity: 1;
}
/* ─────────────────────────────────────────────────── */

/* Sticky Note Direct Editing Fix:
   These styles apply to the bpmn-js direct editing text box.
   We force the background and text color to match the sticky note
   aesthetics during the active edit phase. */
.bpmn-canvas .djs-direct-editing-parent {
	background-color: #fff9c4 !important; /* Pastel yellow */
	border: 1px solid #eab308 !important;   /* yellow-500 border */
	border-radius: 2px;
	padding: 4px;
	box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.bpmn-canvas .djs-direct-editing-content {
	color: #000000 !important;             /* Black text */
	font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
	font-size: 13px !important;
	line-height: 1.2 !important;
	outline: none !important;
}

/* Ensure placeholder/empty state is legible */
.bpmn-canvas .djs-direct-editing-content:empty:before {
	color: rgba(0,0,0,0.3);
}
/* ── Properties Panel Transitions ── */
.slide-right-enter-active, .slide-right-leave-active {
	transition: transform 0.3s ease, opacity 0.3s ease;
}
.slide-right-enter-from, .slide-right-leave-to {
	transform: translateX(100%);
	opacity: 0;
}

/* Ensure the properties panel content doesn't break when width is narrow */
.properties-panel-container .bio-properties-panel {
	min-width: 320px; /* Standard properties panel width target */
}

@media (max-width: 767px) {
	.properties-panel-container .bio-properties-panel {
		min-width: unset;
		width: 100%;
	}
}

/* Custom scrollbar-hide utility if not already global */
.scrollbar-hide::-webkit-scrollbar {
	display: none;
}
.scrollbar-hide {
	-ms-overflow-style: none;
	scrollbar-width: none;
}

/* ── Mobile: touch-friendly BPMN elements ── */
@media (max-width: 639px) {
	/* Make palette slightly transparent so canvas is visible behind it */
	.bpmn-canvas .djs-palette {
		background-color: rgba(255, 255, 255, 0.95);
		box-shadow: 2px 0 8px rgba(0, 0, 0, 0.08);
	}

	/* Ensure context pad sits above everything */
	.djs-context-pad {
		z-index: 200 !important;
	}

	/* Touch-friendly context pad entries */
	.djs-context-pad .entry {
		width: 36px;
		height: 36px;
		touch-action: manipulation;
	}

	/* The popup menu (element type selection) must be fully visible and scrollable */
	.djs-popup {
		z-index: 300 !important;
		max-height: 50vh;
		overflow-y: auto !important;
		-webkit-overflow-scrolling: touch;
	}

	/* Thicker selection outline for touch targets */
	.djs-element.selected .djs-outline {
		stroke-width: 3px !important;
	}
}

/* ── Slide-up transition for mobile bottom sheet ── */
.slide-up-enter-active, .slide-up-leave-active {
	transition: transform 0.3s ease, opacity 0.3s ease;
}
.slide-up-enter-from, .slide-up-leave-to {
	transform: translateY(100%);
	opacity: 0;
}
</style>
