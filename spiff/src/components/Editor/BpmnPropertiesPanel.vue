<script setup>
import { inject, toRef } from "vue";
import { Icon } from "@iconify/vue";
import BpmnCommentSection from "./BpmnCommentSection.vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const readonly = toRef(ed.props, "readonly");
const {
	dragHandleRef,
	dragOffset,
	isDragging,
	isMobile,
	panelReleased,
	propertiesCollapsed,
	propertiesContainer,
	showPropertiesPanel,
	showTimeline,
} = ed;
</script>

<template>
	<!-- Properties Panel -->
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
				'properties-panel-container bg-white z-[60] transition-[width,transform] duration-300 ease-in-out flex flex-col',
				// Mobile: bottom sheet
				isMobile
					? 'fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 max-h-[85vh] overflow-hidden'
					: 'absolute inset-y-0 right-0 border-l border-gray-200 md:relative',
				// Desktop: collapse behavior
				!isMobile && propertiesCollapsed
					? 'w-0 overflow-hidden'
					: !isMobile
						? 'w-full md:w-96 overflow-auto'
						: '',
				{
					'properties-panel--readonly': readonly,
					'properties-panel--released': panelReleased,
				},
			]"
			:style="
				isDragging
					? {
							transform: `translateY(${dragOffset}px)`,
							transition: 'none',
							willChange: 'transform',
						}
					: {}
			"
		>
			<!-- Header (Desktop & Mobile) -->
			<div
				class="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50/50 shrink-0"
			>
				<h3 class="text-sm font-semibold text-gray-900 flex items-center gap-2">
					<Icon icon="lucide:settings" class="w-4 h-4 text-gray-500" />
					Properties
				</h3>
				<div class="flex items-center gap-1">
					<button
						v-if="isMobile"
						class="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors ml-1"
						@click="showPropertiesPanel = false"
					>
						<Icon icon="lucide:x" class="w-5 h-5" />
					</button>
				</div>
			</div>

			<!-- Mobile: Drag handle -->
			<div
				v-if="isMobile"
				class="flex-none flex justify-center py-2 border-b border-gray-100"
			>
				<div
					ref="dragHandleRef"
					class="w-10 h-1 bg-gray-300 rounded-full cursor-grab active:cursor-grabbing"
				></div>
			</div>

			<!-- Properties Content (Scrollable) -->
			<div class="flex-1 overflow-y-auto flex flex-col min-h-0">
				<div
					ref="propertiesContainer"
					:class="[
						'flex-none min-w-0 transition-opacity duration-200',
						!isMobile && propertiesCollapsed
							? 'opacity-0 pointer-events-none'
							: 'opacity-100',
					]"
				>
					<!-- Content is injected here by bpmn-js-properties-panel -->
				</div>

				<BpmnCommentSection v-if="showTimeline" />
			</div>
			<!-- Closes flex-1 overflow-y-auto -->
		</div>
	</transition>
</template>
