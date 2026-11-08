<script setup>
import { inject } from "vue";
import { EDITOR_KEY } from "./useEditorState";

const ed = inject(EDITOR_KEY);
const {
	activeMentionContext,
	closeInlineComment,
	handleInlineCommentInput,
	inlineCommentFormData,
	inlineCommentOverlayTarget,
	inlineCommentPopoverEl,
	inlineMentionedUsers,
	mentionSuggestions,
	selectMention,
	showInlineCommentPopover,
	showMentionDropdown,
	submitInlineComment,
} = ed;
</script>

<template>
	<!-- Inline Comment Popover (Teleported to bpmn-js overlay) -->
	<Teleport
		v-if="showInlineCommentPopover && inlineCommentOverlayTarget"
		:to="inlineCommentOverlayTarget"
	>
		<div
			ref="inlineCommentPopoverEl"
			class="bg-white border border-gray-200 rounded-lg shadow-xl p-3 w-72 space-y-3 z-[150]"
		>
			<div class="space-y-1 relative">
				<textarea
					v-model="inlineCommentFormData.text"
					placeholder="Add a comment..."
					class="inline-comment-textarea w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[60px] resize-none overflow-hidden leading-relaxed"
					:class="{ 'pb-10': inlineMentionedUsers.length > 0 }"
					@input="handleInlineCommentInput"
					@keydown.enter.meta.prevent="submitInlineComment"
					@keydown.enter.ctrl.prevent="submitInlineComment"
				></textarea>

				<!-- Mentions Dropdown -->
				<div
					v-if="showMentionDropdown && activeMentionContext === 'inline'"
					class="mentions-container absolute z-[160] w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1 left-0 top-full mt-1"
				>
					<div
						v-for="u in mentionSuggestions"
						:key="u.value"
						class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
						@click="selectMention(u)"
					>
						<span>{{ u.label }}</span>
					</div>
				</div>
			</div>

			<div
				v-if="inlineMentionedUsers.length > 0"
				class="flex items-center gap-2 pt-1 border-t border-gray-100 mt-2"
			>
				<label
					class="flex items-center gap-2 cursor-pointer select-none text-xs text-gray-700"
				>
					<input
						v-model="inlineCommentFormData.is_task"
						type="checkbox"
						class="rounded border-gray-300 text-blue-600 focus:ring-blue-500 w-3.5 h-3.5"
					/>
					<span>Assign to</span>

					<select
						v-if="inlineMentionedUsers.length > 1"
						v-model="inlineCommentFormData.assigned_to"
						class="text-xs border border-gray-200 rounded px-1 py-0.5 ml-1 bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-400"
					>
						<option v-for="u in inlineMentionedUsers" :key="u.value" :value="u.value">
							{{ u.label }}
						</option>
					</select>
					<span v-else class="font-medium ml-1 text-blue-700">{{
						inlineMentionedUsers[0]?.label
					}}</span>
				</label>
			</div>

			<div class="flex justify-end gap-2 pt-1">
				<Button
					size="sm"
					variant="subtle"
					class="text-xs py-1"
					@click="closeInlineComment(true)"
				>
					Cancel
				</Button>
				<Button
					size="sm"
					variant="solid"
					:disabled="!inlineCommentFormData.text"
					class="text-xs py-1"
					@click="submitInlineComment"
				>
					Post Comment
				</Button>
			</div>
		</div>
	</Teleport>
</template>
