<script setup>
import { inject, toRef } from "vue";
import { Icon } from "@iconify/vue";
import FormattingToolbar from "@/components/Editor/FormattingToolbar.vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const readonly = toRef(ed.props, "readonly");
const {
	canRedo,
	canUndo,
	deleteSelected,
	isMobile,
	isMounted,
	modelerInstance,
	redo,
	selectedElements,
	showMobileFormatPopover,
	undo,
} = ed;
</script>

<template>
	<!-- Mobile Floating Toolbar (Undo/Redo/Delete/Format) -->
	<transition name="fade">
		<div
			v-if="isMobile && !readonly && isMounted"
			class="fixed bottom-14 left-1/2 -translate-x-1/2 z-[45] bg-white/95 backdrop-blur rounded-full shadow-lg border border-gray-200 flex items-center gap-1 px-2 py-1.5"
		>
			<button
				:disabled="!canUndo"
				:class="[
					'min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors',
					canUndo ? 'text-gray-700 active:bg-gray-100' : 'text-gray-300',
				]"
				@click="undo"
			>
				<Icon icon="lucide:undo-2" class="w-5 h-5" />
			</button>
			<button
				:disabled="!canRedo"
				:class="[
					'min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors',
					canRedo ? 'text-gray-700 active:bg-gray-100' : 'text-gray-300',
				]"
				@click="redo"
			>
				<Icon icon="lucide:redo-2" class="w-5 h-5" />
			</button>
			<div class="w-px h-6 bg-gray-200 mx-0.5"></div>
			<button
				class="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-gray-700 active:bg-gray-100 transition-colors"
				@click="deleteSelected"
			>
				<Icon icon="lucide:trash-2" class="w-5 h-5" />
			</button>
			<div class="w-px h-6 bg-gray-200 mx-0.5"></div>
			<!-- Format button - opens formatting popover -->
			<div class="relative">
				<button
					:class="[
						'min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-colors',
						showMobileFormatPopover
							? 'bg-blue-100 text-blue-700'
							: 'text-gray-700 active:bg-gray-100',
					]"
					@click="showMobileFormatPopover = !showMobileFormatPopover"
				>
					<Icon icon="lucide:palette" class="w-5 h-5" />
				</button>
				<!-- Format popover -->
				<transition name="fade">
					<div
						v-if="showMobileFormatPopover"
						v-click-outside="() => (showMobileFormatPopover = false)"
						class="absolute bottom-full right-0 mb-2 bg-white border border-gray-200 rounded-xl shadow-xl p-2 z-[100] min-w-[280px]"
					>
						<FormattingToolbar
							:selected-elements="selectedElements"
							:modeler="modelerInstance"
						/>
					</div>
				</transition>
			</div>
		</div>
	</transition>
</template>
