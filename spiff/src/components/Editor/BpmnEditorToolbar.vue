<script setup>
import { inject, toRef } from "vue";
import { Icon } from "@iconify/vue";
import FormattingToolbar from "@/components/Editor/FormattingToolbar.vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const readonly = toRef(ed.props, "readonly");
const saveStatusColor = toRef(ed.props, "saveStatusColor");
const saveStatusText = toRef(ed.props, "saveStatusText");
const {
	addStickyNote,
	canRedo,
	canUndo,
	deleteSelected,
	isCommentMode,
	isMounted,
	modelerInstance,
	redo,
	selectedElements,
	showMoreTools,
	showProsAllyPanel,
	toggleCommentMode,
	toolbarEl,
	undo,
} = ed;
</script>

<template>
	<!-- Toolbar (moved natively to parent Editor.vue's header) -->
	<div
		v-show="isMounted"
		ref="toolbarEl"
		class="bpmn-toolbar relative flex items-center gap-1.5 w-full h-full text-gray-700 flex-nowrap min-w-0 pr-2"
	>
		<template v-if="!readonly">
			<div
				:class="[
					'bpmn-toolbar-tools flex items-center gap-1.5',
					{ 'bpmn-toolbar-tools--open': showMoreTools },
				]"
			>
				<!-- Undo/Redo buttons -->
				<button
					title="Undo (Ctrl+Z)"
					:disabled="!canUndo"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						canUndo
							? 'hover:bg-gray-100 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
					@click="undo"
				>
					<Icon icon="lucide:undo-2" class="w-4 h-4" />
				</button>
				<button
					title="Redo (Ctrl+Y)"
					:disabled="!canRedo"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						canRedo
							? 'hover:bg-gray-100 text-gray-700'
							: 'text-gray-300 cursor-not-allowed',
					]"
					@click="redo"
				>
					<Icon icon="lucide:redo-2" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Delete button -->
				<button
					title="Delete (Del)"
					class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
					@click="deleteSelected"
				>
					<Icon icon="lucide:trash-2" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Sticky Note button -->
				<button
					title="Add Sticky Note"
					class="p-1.5 flex items-center justify-center rounded hover:bg-gray-100 text-gray-700 transition-colors"
					@click="addStickyNote"
				>
					<Icon icon="lucide:sticky-note" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Comment Tool button -->
				<button
					title="Comment Tool"
					:class="[
						'p-1.5 flex items-center justify-center rounded transition-colors',
						isCommentMode
							? 'bg-blue-100 text-blue-700 shadow-sm'
							: 'hover:bg-gray-100 text-gray-700',
					]"
					@click="toggleCommentMode"
				>
					<Icon icon="lucide:message-square" class="w-4 h-4" />
				</button>

				<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

				<!-- Formatting Toolbar -->
				<FormattingToolbar
					:selected-elements="selectedElements"
					:modeler="modelerInstance"
					class="bpmn-toolbar-format shrink-0"
				/>
			</div>

			<!-- Shown only when the toolbar is too narrow; opens the folded formatting tools as a panel -->
			<button
				title="Formatting"
				:class="[
					'bpmn-toolbar-more p-1.5 items-center justify-center rounded transition-colors shrink-0',
					showMoreTools
						? 'bg-blue-100 text-blue-700'
						: 'hover:bg-gray-100 text-gray-700',
				]"
				@click="showMoreTools = !showMoreTools"
			>
				<Icon icon="lucide:palette" class="w-4 h-4" />
			</button>
		</template>

		<!-- Read-only indicator -->
		<div v-if="readonly" class="flex items-center gap-1.5 text-gray-400 text-sm">
			<Icon icon="lucide:lock" class="w-4 h-4" />
			<span>View Only</span>
		</div>

		<div class="flex-1 flex items-center justify-end gap-2 px-3">
			<div
				v-if="saveStatusText && !readonly"
				class="text-sm font-medium transition-colors"
				:class="saveStatusColor"
			>
				{{ saveStatusText }}
			</div>

			<!-- ProsAlly Toggle Button - hidden while read-only, since any
		     diagram it generates would be discarded by the change guard. -->
			<button
				v-if="!readonly"
				title="ProsAlly AI Assistant"
				:class="[
					'flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors text-xs font-semibold shrink-0',
					showProsAllyPanel
						? 'bg-violet-100 text-violet-700 shadow-sm'
						: 'hover:bg-gray-100 text-gray-600 border border-gray-200',
				]"
				@click="showProsAllyPanel = !showProsAllyPanel"
			>
				<Icon icon="lucide:sparkles" class="w-3.5 h-3.5" />
				<span class="bpmn-toolbar-label hidden sm:inline">ProsAlly</span>
			</button>
		</div>
	</div>
</template>

<style scoped>
/* The toolbar shares the header with the title and actions, so it folds by its own width, not the viewport's. */
.bpmn-toolbar {
	container-type: inline-size;
}
.bpmn-toolbar-more {
	display: none;
}
@container (max-width: 879px) {
	.bpmn-toolbar-more {
		display: flex;
	}
	.bpmn-toolbar .bpmn-toolbar-tools {
		position: relative;
	}
	.bpmn-toolbar .bpmn-toolbar-format {
		display: none;
	}
	.bpmn-toolbar .bpmn-toolbar-tools--open .bpmn-toolbar-format {
		display: flex;
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 70;
		padding: 8px;
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
	}
}
@container (max-width: 469px) {
	.bpmn-toolbar .bpmn-toolbar-tools {
		display: none;
	}
	.bpmn-toolbar .bpmn-toolbar-tools.bpmn-toolbar-tools--open {
		display: flex;
		flex-wrap: wrap;
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 70;
		width: 320px;
		padding: 8px;
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
	}
	.bpmn-toolbar .bpmn-toolbar-tools--open .bpmn-toolbar-format {
		flex-wrap: wrap;
		flex-basis: 100%;
		position: static;
		padding: 0;
		border: 0;
		box-shadow: none;
	}
	.bpmn-toolbar .bpmn-toolbar-label {
		display: none;
	}
}
</style>
