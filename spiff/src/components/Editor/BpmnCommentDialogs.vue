<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import { EDITOR_KEY } from "./useEditorState";

const ed = inject(EDITOR_KEY);
const {
	activeCommentElement,
	activeMentionContext,
	commentFormData,
	filteredUsers,
	handleCommentInput,
	mentionSuggestions,
	resolveComment,
	selectMention,
	selectedElementComments,
	showCommentDialog,
	showMentionDropdown,
	showUserDropdown,
	showViewCommentsDialog,
	submitComment,
	userSearchQuery,
} = ed;
</script>

<template>
	<!-- Comment Dialog -->
	<Dialog v-model="showCommentDialog" :options="{ title: 'Add Comment' }">
		<template #body-content>
			<div class="space-y-4">
				<div
					v-if="activeCommentElement"
					class="text-xs text-gray-500 bg-gray-50 p-2 rounded border border-gray-100 italic"
				>
					Attaching to:
					{{ activeCommentElement.businessObject?.name || activeCommentElement.id }}
				</div>

				<div class="relative">
					<FormControl
						v-model="commentFormData.text"
						label="Comment"
						type="textarea"
						:required="true"
						placeholder="What's on your mind?"
						class="main-comment-textarea"
						@input="handleCommentInput"
						@keydown.enter.meta.prevent="submitComment"
						@keydown.enter.ctrl.prevent="submitComment"
					/>
					<div
						v-if="showMentionDropdown && activeMentionContext === 'dialog'"
						v-click-outside="
							() => {
								showMentionDropdown = false;
							}
						"
						class="absolute z-[120] w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1 left-0 top-full mt-1"
					>
						<div
							v-for="u in mentionSuggestions"
							:key="u.value"
							class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
							@click="selectMention(u)"
						>
							<span>{{ u.label }}</span>
						</div>
						<div
							v-if="mentionSuggestions.length === 0"
							class="px-3 py-1.5 text-xs text-gray-400 italic"
						>
							No users found
						</div>
					</div>
				</div>

				<div class="flex items-center gap-4">
					<div class="flex-1">
						<div class="space-y-1">
							<label class="block text-xs font-medium text-gray-700"
								>Assign To</label
							>
							<div class="relative">
								<Icon
									icon="lucide:search"
									class="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400"
								/>
								<input
									v-model="userSearchQuery"
									type="text"
									placeholder="Search users..."
									class="w-full pl-9 pr-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
									@focus="showUserDropdown = true"
								/>
								<div
									v-if="showUserDropdown && filteredUsers.length > 0"
									v-click-outside="() => (showUserDropdown = false)"
									class="absolute z-[110] w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1"
								>
									<div
										v-for="u in filteredUsers"
										:key="u.value"
										class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
										@click="
											commentFormData.assigned_to = u.value;
											userSearchQuery = u.label;
											showUserDropdown = false;
										"
									>
										<span>{{ u.label }}</span>
										<Icon
											v-if="commentFormData.assigned_to === u.value"
											icon="lucide:check"
											class="w-3.5 h-3.5 text-blue-600"
										/>
									</div>
								</div>
								<div
									v-else-if="
										showUserDropdown &&
										userSearchQuery &&
										filteredUsers.length === 0
									"
									class="absolute z-[110] w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg p-3 text-xs text-gray-400 italic"
								>
									No users found
								</div>
							</div>
						</div>
					</div>
					<div class="pt-6">
						<label
							class="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-700"
						>
							<input
								v-model="commentFormData.is_task"
								type="checkbox"
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
				<Button variant="solid" :disabled="!commentFormData.text" @click="submitComment"
					>Post Comment</Button
				>
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
							<span class="text-xs font-semibold text-gray-700">{{
								comment.author
							}}</span>
						</div>
						<span class="text-[10px] text-gray-400 italic">
							{{
								new Date(
									comment.creation
										.replace(" ", "T")
										.replace(/(\.\d{3})\d+$/, "$1"),
								).toLocaleString()
							}}
						</span>
					</div>

					<p class="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
						{{ comment.comment }}
					</p>

					<div
						v-if="comment.is_task && comment.status"
						class="flex items-center justify-between pt-2 border-t border-gray-50 mt-2"
					>
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
							class="text-green-600 hover:bg-green-50"
							@click="resolveComment(comment)"
						>
							Resolve
						</Button>
					</div>
				</div>

				<div
					v-if="selectedElementComments.length === 0"
					class="text-center py-8 text-gray-400 italic text-sm"
				>
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
</template>
