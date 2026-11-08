<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const {
	addCommentFromContextMenu,
	canAddComment,
	contextMenuElementCommentCount,
	contextMenuPosition,
	showContextMenu,
	viewCommentsFromContextMenu,
} = ed;
</script>

<template>
	<!-- Right-Click Context Menu -->
	<div
		v-if="showContextMenu"
		data-context-menu
		class="fixed z-[200] bg-white border border-gray-200 rounded-lg shadow-xl py-1 min-w-[180px]"
		:style="{ left: contextMenuPosition.x + 'px', top: contextMenuPosition.y + 'px' }"
	>
		<button
			v-if="canAddComment"
			class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-blue-50 transition-colors"
			@click="addCommentFromContextMenu"
		>
			<Icon icon="lucide:message-square-plus" class="w-4 h-4" />
			Add Comment
		</button>
		<button
			v-if="contextMenuElementCommentCount > 0"
			class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-blue-50 transition-colors"
			@click="viewCommentsFromContextMenu"
		>
			<Icon icon="lucide:messages-square" class="w-4 h-4" />
			View Comments ({{ contextMenuElementCommentCount }})
		</button>
	</div>
</template>
