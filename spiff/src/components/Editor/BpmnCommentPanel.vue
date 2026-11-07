<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import { getCommentAvatarColor, getCommentInitials } from "@/utils/avatar";
import { EDITOR_KEY } from "./useEditorState";

const ed = inject(EDITOR_KEY);
const {
	activeMentionContext,
	comments,
	currentElementComments,
	formatCommentDate,
	handleTimelineCommentInput,
	isMobile,
	mentionSuggestions,
	navigateToElementComments,
	propertiesCollapsed,
	resolveComment,
	selectMention,
	selectedElements,
	showMentionDropdown,
	showPropertiesPanel,
	showTimeline,
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
	<!-- Standalone Comment Panel (only when properties panel is closed or collapsed) -->
	<transition name="slide-right">
		<div
			v-show="showTimeline && (!showPropertiesPanel || (!isMobile && propertiesCollapsed))"
			:class="[
				'comment-panel-container bg-white z-[59] transition-[width,transform] duration-300 ease-in-out flex flex-col',
				isMobile
					? 'fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 max-h-[85vh] overflow-hidden'
					: 'absolute inset-y-0 right-0 border-l border-gray-200 md:relative w-full md:w-96 overflow-hidden',
			]"
		>
			<!-- Comment Panel Header -->
			<div
				class="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50/50 shrink-0"
			>
				<h3 class="text-sm font-semibold text-gray-900 flex items-center gap-2">
					<Icon icon="lucide:message-square" class="w-4 h-4 text-gray-500" />
					Comments
					<span
						v-if="comments.length > 0"
						class="ml-1 px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-bold rounded-full"
						>{{ comments.length }}</span
					>
				</h3>
				<div class="flex items-center gap-1">
					<!-- Filters -->
					<div
						class="flex items-center gap-1 bg-white border border-gray-200 p-0.5 rounded-md shadow-sm mr-1"
					>
						<button
							class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight"
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
								:icon="
									timelineTaskFilter ? 'lucide:check-circle' : 'lucide:circle'
								"
								class="w-3 h-3"
							/>
							Tasks
						</button>
						<button
							class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight"
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
						<!-- Shape filter pill: shows when an element is selected -->
						<button
							v-if="selectedElements.length > 0"
							class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight max-w-[80px]"
							:class="
								timelineFilterMode === 'element'
									? 'bg-violet-100 text-violet-700'
									: 'text-gray-400 hover:text-gray-600'
							"
							:title="`Filter by: ${selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Selected'}`"
							@click="
								timelineFilterMode =
									timelineFilterMode === 'element' ? 'all' : 'element'
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
					<button
						class="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors"
						title="Close"
						@click="showTimeline = false"
					>
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>
			</div>

			<!-- Comment Input -->
			<div class="p-3 border-b border-gray-100 bg-white shrink-0 shadow-sm">
				<div class="relative">
					<textarea
						v-model="timelineText"
						placeholder="Add a comment..."
						class="timeline-textarea w-full px-3 py-2 text-xs border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[60px] resize-none overflow-hidden pr-10 bg-gray-50/30 leading-relaxed"
						:class="{ 'pb-10': timelineMentionedUsers.length > 0 }"
						@input="handleTimelineCommentInput"
						@keydown.enter.meta.prevent="submitTimelineComment"
						@keydown.enter.ctrl.prevent="submitTimelineComment"
					></textarea>

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

					<!-- Quick Comment Actions -->
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
								class="w-4 h-4"
							/>
						</button>
						<button
							:disabled="!timelineText.trim()"
							class="p-1 rounded-md text-blue-600 hover:bg-blue-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
							@click="submitTimelineComment"
						>
							<Icon icon="lucide:send" class="w-4.5 h-4.5" />
						</button>
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
				<div class="mt-1 flex items-center justify-between px-1">
					<span class="text-[9px] text-gray-400 flex items-center gap-1">
						<Icon icon="lucide:command" class="w-2.5 h-2.5" />
						+ Enter to post
					</span>
					<span
						v-if="timelineIsTask"
						class="text-[9px] font-bold text-orange-500 uppercase tracking-tighter"
						>Creating Task</span
					>
				</div>
			</div>

			<!-- Comment List -->
			<div class="flex-1 overflow-y-auto p-4 space-y-6">
				<div
					v-if="currentElementComments.length === 0"
					class="flex flex-col items-center justify-center py-10 text-gray-400"
				>
					<Icon icon="lucide:message-square" class="w-8 h-8 opacity-20 mb-2" />
					<p class="text-xs">No comments yet</p>
				</div>

				<div
					v-for="(c, idx) in sortedTimelineComments"
					:key="c.name"
					class="relative pl-8 group transition-colors rounded-md p-1.5 -mx-1.5"
					:class="
						c.element_id && c.element_id !== 'process'
							? 'cursor-pointer hover:bg-gray-50'
							: ''
					"
					@click="navigateToElementComments(c.element_id)"
				>
					<!-- Vertical Line -->
					<div
						v-if="idx < sortedTimelineComments.length - 1"
						class="absolute left-[5px] top-[14px] bottom-[-24px] w-0.5 bg-gray-100"
					></div>

					<!-- Avatar -->
					<div
						class="absolute left-0 top-[6px] w-6.5 h-6.5 rounded-full border-2 border-white shadow-sm z-10 flex items-center justify-center overflow-hidden -translate-x-1"
					>
						<img
							v-if="c.owner_image"
							:src="c.owner_image"
							class="w-full h-full object-cover"
						/>
						<div
							v-else
							:class="[
								'w-full h-full flex items-center justify-center text-[8px] font-bold text-white',
								getCommentAvatarColor(c.owner),
							]"
						>
							{{ getCommentInitials(c.owner_full_name || c.owner || c.author) }}
						</div>
					</div>

					<div class="space-y-1.5">
						<div class="flex items-center justify-between">
							<div class="flex items-center gap-2">
								<span class="text-xs font-bold text-gray-900">{{
									c.owner_full_name || c.owner || c.author
								}}</span>
								<span
									v-if="c.is_task"
									class="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 text-[9px] font-bold uppercase"
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
							<span class="text-[10px] text-gray-400 font-medium">{{
								formatCommentDate(c.creation)
							}}</span>
						</div>
						<p class="text-xs text-gray-600 leading-relaxed whitespace-pre-wrap">
							{{ c.comment }}
						</p>

						<!-- Task status -->
						<div
							v-if="c.is_task && c.status"
							class="flex items-center justify-between pt-1"
						>
							<div class="flex items-center gap-2">
								<Badge
									:label="c.status"
									:theme="c.status === 'Open' ? 'orange' : 'green'"
									size="sm"
									class="!text-[9px] !px-1.5"
								/>
								<span v-if="c.assigned_to" class="text-[10px] text-gray-500"
									>assigned to
									{{ c.assigned_to_full_name || c.assigned_to }}</span
								>
							</div>
							<button
								v-if="c.status === 'Open'"
								class="text-[10px] font-medium text-green-600 hover:bg-green-50 px-2 py-0.5 rounded transition-colors"
								@click.stop="resolveComment(c)"
							>
								Resolve
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</transition>
</template>
