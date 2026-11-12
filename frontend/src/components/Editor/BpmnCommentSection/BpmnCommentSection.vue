<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import { getCommentAvatarColor, getCommentInitials } from "@/utils/avatar";
import { EDITOR_KEY } from "@/composables/Editor/useEditorState";

const ed = inject(EDITOR_KEY);
const {
	activeMentionContext,
	comments,
	currentElementComments,
	formatCommentDate,
	handleTimelineCommentInput,
	mentionSuggestions,
	navigateToElementComments,
	resolveComment,
	selectMention,
	selectedElements,
	showMentionDropdown,
	sortedTimelineComments,
	submitTimelineComment,
	timelineAssignedFilter,
	timelineAssignedTo,
	timelineFilterMode,
	timelineIsTask,
	timelineMentionedUsers,
	timelineTaskFilter,
	timelineText,
} = ed;
</script>

<template>
	<div class="border-t border-gray-200 flex-1 flex flex-col min-h-[300px]">
		<!-- Comment Section Header with filters -->
		<div
			class="flex items-center justify-between px-4 py-2.5 bg-white border-b border-gray-200 shrink-0"
		>
			<h3
				class="text-[11px] font-bold text-gray-700 uppercase tracking-wider flex items-center gap-1.5"
			>
				<Icon icon="lucide:message-square" class="w-3.5 h-3.5" />
				Comments
				<span
					v-if="comments.length > 0"
					class="ml-0.5 px-1 py-0.5 bg-blue-100 text-blue-700 text-[9px] font-bold rounded-full"
					>{{ comments.length }}</span
				>
			</h3>
			<div
				class="flex items-center gap-1 bg-white border border-gray-200 p-0.5 rounded-md shadow-sm"
			>
				<button
					class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight"
					:class="
						timelineTaskFilter
							? 'bg-orange-100 text-orange-700'
							: 'text-gray-400 hover:text-gray-600'
					"
					title="Show open tasks only"
					@click="
						timelineTaskFilter = !timelineTaskFilter;
						if (timelineTaskFilter) timelineAssignedFilter = false;
					"
				>
					<Icon
						:icon="timelineTaskFilter ? 'lucide:check-circle' : 'lucide:circle'"
						class="w-3 h-3"
					/>
					Tasks
				</button>
				<button
					class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight"
					:class="
						timelineAssignedFilter
							? 'bg-blue-100 text-blue-700'
							: 'text-gray-400 hover:text-gray-600'
					"
					title="Show only assigned to me"
					@click="
						timelineAssignedFilter = !timelineAssignedFilter;
						if (timelineAssignedFilter) {
							timelineTaskFilter = false;
							timelineFilterMode = 'all';
						}
					"
				>
					<Icon icon="lucide:user" class="w-3 h-3" />
					Mine
				</button>
				<button
					v-if="selectedElements.length > 0"
					class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight max-w-[80px]"
					:class="
						timelineFilterMode === 'element'
							? 'bg-violet-100 text-violet-700'
							: 'text-gray-400 hover:text-gray-600'
					"
					:title="`Filter by: ${selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Selected'}`"
					@click="
						timelineFilterMode = timelineFilterMode === 'element' ? 'all' : 'element'
					"
				>
					<Icon icon="lucide:crosshair" class="w-3 h-3 shrink-0" />
					<span class="truncate">{{
						selectedElements[0]?.businessObject?.name ||
						selectedElements[0]?.id ||
						"Shape"
					}}</span>
				</button>
			</div>
		</div>

		<!-- Comment Input -->
		<div class="p-3 border-b border-gray-100 bg-white shrink-0">
			<div class="relative">
				<textarea
					v-model="timelineText"
					placeholder="Add a comment..."
					class="timeline-textarea w-full px-3 py-2 text-xs border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[52px] resize-none overflow-hidden pr-10 bg-gray-50/30 leading-relaxed"
					:class="{ 'pb-10': timelineMentionedUsers.length > 0 }"
					@input="handleTimelineCommentInput"
					@keydown.enter.meta.prevent="submitTimelineComment"
					@keydown.enter.ctrl.prevent="submitTimelineComment"
				></textarea>
				<div class="absolute right-2 bottom-2 flex items-center gap-1.5">
					<button
						class="p-1 rounded-md transition-colors"
						:class="
							timelineIsTask
								? 'bg-orange-100 text-orange-600'
								: 'text-gray-400 hover:bg-gray-100'
						"
						title="Mark as Task"
						@click="timelineIsTask = !timelineIsTask"
					>
						<Icon
							:icon="timelineIsTask ? 'lucide:check-square' : 'lucide:square'"
							class="w-3.5 h-3.5"
						/>
					</button>
					<button
						:disabled="!timelineText.trim()"
						class="p-1 rounded-md text-blue-600 hover:bg-blue-50 disabled:opacity-30 transition-colors"
						@click="submitTimelineComment"
					>
						<Icon icon="lucide:send" class="w-3.5 h-3.5" />
					</button>
				</div>

				<!-- Timeline Mentions Dropdown -->
				<div
					v-if="showMentionDropdown && activeMentionContext === 'timeline'"
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

				<!-- Assignment Indicator -->
				<div
					v-if="timelineMentionedUsers.length > 0"
					class="absolute left-2.5 bottom-2.5 flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-blue-50 border border-blue-100 text-[10px] text-blue-700 shadow-sm pr-1"
				>
					<Icon icon="lucide:user" class="w-3 h-3" />
					<select
						v-if="timelineMentionedUsers.length > 1"
						v-model="timelineAssignedTo"
						class="text-[10px] bg-transparent border-none p-0 focus:ring-0 text-blue-700 font-medium cursor-pointer"
					>
						<option
							v-for="u in timelineMentionedUsers"
							:key="u.value"
							:value="u.value"
						>
							{{ u.label }}
						</option>
					</select>
					<span v-else class="max-w-[100px] truncate pr-2">{{
						timelineMentionedUsers[0]?.label
					}}</span>
					<button
						class="ml-0.5 p-0.5 hover:bg-blue-100 rounded-full text-blue-400 hover:text-blue-600"
						@click="
							timelineAssignedTo = '';
							timelineMentionedUsers = [];
						"
					>
						<Icon icon="lucide:x" class="w-2.5 h-2.5" />
					</button>
				</div>
			</div>
		</div>

		<!-- Comment List -->
		<div class="flex-1 overflow-y-auto p-3 space-y-4">
			<div
				v-if="currentElementComments.length === 0"
				class="flex flex-col items-center justify-center py-6 text-gray-400"
			>
				<Icon icon="lucide:message-square" class="w-6 h-6 opacity-20 mb-1" />
				<p class="text-[11px]">No comments yet</p>
			</div>
			<div
				v-for="(c, idx) in sortedTimelineComments"
				:key="c.name"
				class="relative pl-7 group transition-colors rounded-md p-1 -mx-1"
				:class="
					c.element_id && c.element_id !== 'process'
						? 'cursor-pointer hover:bg-gray-50'
						: ''
				"
				@click="navigateToElementComments(c.element_id)"
			>
				<div
					v-if="idx < sortedTimelineComments.length - 1"
					class="absolute left-[4px] top-[12px] bottom-[-16px] w-0.5 bg-gray-100"
				></div>
				<div
					class="absolute left-0 top-[4px] w-5 h-5 rounded-full border-2 border-white shadow-sm z-10 flex items-center justify-center overflow-hidden"
				>
					<img
						v-if="c.owner_image"
						:src="c.owner_image"
						class="w-full h-full object-cover"
					/>
					<div
						v-else
						:class="[
							'w-full h-full flex items-center justify-center text-[7px] font-bold text-white',
							getCommentAvatarColor(c.owner),
						]"
					>
						{{ getCommentInitials(c.owner_full_name || c.owner || c.author) }}
					</div>
				</div>
				<div class="space-y-1">
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-1.5">
							<span class="text-[11px] font-bold text-gray-900">{{
								c.owner_full_name || c.owner || c.author
							}}</span>
							<span
								v-if="c.is_task"
								class="px-1 py-0.5 rounded bg-orange-100 text-orange-700 text-[8px] font-bold uppercase"
								>Task</span
							>
							<span
								v-if="
									timelineFilterMode === 'all' &&
									c.element_id &&
									c.element_id !== 'process'
								"
								class="px-1 py-0.5 rounded bg-gray-100 text-gray-500 text-[8px] font-medium"
								>@{{ c.element_id }}</span
							>
						</div>
						<span class="text-[9px] text-gray-400">{{
							formatCommentDate(c.creation)
						}}</span>
					</div>
					<p class="text-[11px] text-gray-600 leading-relaxed whitespace-pre-wrap">
						{{ c.comment }}
					</p>
					<div
						v-if="c.is_task && c.status"
						class="flex items-center justify-between pt-0.5"
					>
						<div class="flex items-center gap-1.5">
							<Badge
								:label="c.status"
								:theme="c.status === 'Open' ? 'orange' : 'green'"
								size="sm"
								class="!text-[8px] !px-1"
							/>
							<span v-if="c.assigned_to" class="text-[9px] text-gray-500"
								>assigned to {{ c.assigned_to_full_name || c.assigned_to }}</span
							>
						</div>
						<button
							v-if="c.status === 'Open'"
							class="text-[9px] font-medium text-green-600 hover:bg-green-50 px-1.5 py-0.5 rounded transition-colors"
							@click.stop="resolveComment(c)"
						>
							Resolve
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style src="./BpmnCommentSection.css"></style>
