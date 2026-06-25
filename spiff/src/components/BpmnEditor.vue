<template>
	<div class="bpmn-editor-wrapper h-full w-full flex flex-col">
		<!-- Toolbar (moved natively to parent Editor.vue's header) -->
		<div ref="toolbarEl" v-show="isMounted" class="flex items-center gap-1.5 w-full h-full text-gray-700 flex-nowrap min-w-0 pr-2">
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


			<div class="flex-1 min-w-4 flex items-center justify-end gap-2 px-3">
				<div v-if="saveStatusText && !readonly" class="text-sm font-medium transition-colors" :class="saveStatusColor">
					{{ saveStatusText }}
				</div>

				<!-- ProsAlly Toggle Button -->
				<button
					@click="showProsAllyPanel = !showProsAllyPanel"
					title="ProsAlly AI Assistant"
					:class="[
						'flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-colors text-xs font-semibold shrink-0',
						showProsAllyPanel
							? 'bg-violet-100 text-violet-700 shadow-sm'
							: 'hover:bg-gray-100 text-gray-600 border border-gray-200',
					]"
				>
					<Icon icon="lucide:sparkles" class="w-3.5 h-3.5" />
					<span class="hidden sm:inline">ProsAlly</span>
				</button>
			</div>
		</div>



		<!-- Main Content Area -->
		<div :class="['flex-1 flex relative', isMobile ? 'overflow-visible' : 'overflow-hidden']">
			<!-- BPMN Canvas -->
			<div
				ref="container"
				:class="['bpmn-canvas flex-1 min-w-0', { 'bpmn-canvas--readonly': readonly, 'comment-mode-active': isCommentMode }]"
				@contextmenu.prevent
			></div>

			<!-- ProsAlly Panel — flex sibling so canvas shrinks instead of being covered -->
			<transition name="prosally-slide">
				<div
					v-if="showProsAllyPanel && !isMobile"
					class="prosally-panel-container w-[420px] shrink-0 border-l border-gray-200 flex flex-col z-[50]"
				>
					<ProsAllyPanel
						:process-name="processNameForPanel"
						:get-canvas-xml="getCanvasXml"
						@close="showProsAllyPanel = false"
						@bpmn-generated="onProsAllyBpmnGenerated"
					/>
				</div>
			</transition>

			<!-- Mobile: ProsAlly as bottom sheet -->
			<transition name="slide-up">
				<div
					v-if="showProsAllyPanel && isMobile"
					class="fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 bg-white z-[65] flex flex-col"
					style="height: 70vh;"
				>
					<div class="flex justify-center py-2 border-b border-gray-100 shrink-0">
						<div class="w-10 h-1 bg-gray-300 rounded-full"></div>
					</div>
					<ProsAllyPanel
						:process-name="processNameForPanel"
						:get-canvas-xml="getCanvasXml"
						@close="showProsAllyPanel = false"
						@bpmn-generated="onProsAllyBpmnGenerated"
					/>
				</div>
			</transition>
			
			<!-- Inline Comment Popover (Teleported to bpmn-js overlay) -->
			<Teleport v-if="showInlineCommentPopover && inlineCommentOverlayTarget" :to="inlineCommentOverlayTarget">
				<div 
					ref="inlineCommentPopoverEl"
					class="bg-white border border-gray-200 rounded-lg shadow-xl p-3 w-72 space-y-3 z-[150]"
				>
					<div class="space-y-1 relative">
						<textarea
							v-model="inlineCommentFormData.text"
							@input="handleInlineCommentInput"
							@keydown.enter.meta.prevent="submitInlineComment"
							@keydown.enter.ctrl.prevent="submitInlineComment"
							placeholder="Add a comment..."
							class="inline-comment-textarea w-full px-3 py-2 text-sm border border-gray-200 rounded-md focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[60px] resize-none overflow-hidden leading-relaxed"
							:class="{ 'pb-10': inlineMentionedUsers.length > 0 }"
						></textarea>
						
						<!-- Mentions Dropdown -->
						<div
							v-if="showMentionDropdown && activeMentionContext === 'inline'"
							class="mentions-container absolute z-[160] w-full max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg py-1 left-0 top-full mt-1"
						>
							<div
								v-for="u in mentionSuggestions"
								:key="u.value"
								@click="selectMention(u)"
								class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
							>
								<span>{{ u.label }}</span>
							</div>
						</div>
					</div>

					<div v-if="inlineMentionedUsers.length > 0" class="flex items-center gap-2 pt-1 border-t border-gray-100 mt-2">
						<label class="flex items-center gap-2 cursor-pointer select-none text-xs text-gray-700">
							<input
								type="checkbox"
								v-model="inlineCommentFormData.is_task"
								class="rounded border-gray-300 text-blue-600 focus:ring-blue-500 w-3.5 h-3.5"
							/>
							<span>Assign to</span>
							
							<select 
								v-if="inlineMentionedUsers.length > 1"
								v-model="inlineCommentFormData.assigned_to"
								class="text-xs border border-gray-200 rounded px-1 py-0.5 ml-1 bg-gray-50 focus:outline-none focus:ring-1 focus:ring-blue-400"
							>
								<option v-for="u in inlineMentionedUsers" :key="u.value" :value="u.value">{{ u.label }}</option>
							</select>
							<span v-else class="font-medium ml-1 text-blue-700">{{ inlineMentionedUsers[0]?.label }}</span>
						</label>
					</div>

					<div class="flex justify-end gap-2 pt-1">
						<Button 
							size="sm" 
							variant="subtle" 
							@click="closeInlineComment(true)"
							class="text-xs py-1"
						>
							Cancel
						</Button>
						<Button 
							size="sm" 
							variant="solid" 
							@click="submitInlineComment"
							:disabled="!inlineCommentFormData.text"
							class="text-xs py-1"
						>
							Post Comment
						</Button>
					</div>
				</div>
			</Teleport>

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
						'properties-panel-container bg-white z-[60] transition-[width,transform] duration-300 ease-in-out flex flex-col',
						// Mobile: bottom sheet
						isMobile
							? 'fixed inset-x-0 bottom-0 rounded-t-2xl shadow-2xl border-t border-gray-200 max-h-[85vh] overflow-hidden'
							: 'absolute inset-y-0 right-0 border-l border-gray-200 md:relative',
						// Desktop: collapse behavior
						!isMobile && propertiesCollapsed 
							? 'w-0 overflow-hidden' 
							: !isMobile ? 'w-full md:w-96 overflow-auto' : '',
						{ 'properties-panel--readonly': readonly }
					]"
					:style="isDragging ? { transform: `translateY(${dragOffset}px)`, transition: 'none', willChange: 'transform' } : {}"
				>
					<!-- Header (Desktop & Mobile) -->
					<div class="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50/50 shrink-0">
						<h3 class="text-sm font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:settings" class="w-4 h-4 text-gray-500" />
							Properties
						</h3>
						<div class="flex items-center gap-1">
							<button
								v-if="isMobile"
								@click="showPropertiesPanel = false"
								class="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors ml-1"
							>
								<Icon icon="lucide:x" class="w-5 h-5" />
							</button>
						</div>
					</div>

					<!-- Mobile: Drag handle -->
					<div v-if="isMobile" class="flex-none flex justify-center py-2 border-b border-gray-100">
						<div ref="dragHandleRef" class="w-10 h-1 bg-gray-300 rounded-full cursor-grab active:cursor-grabbing"></div>
					</div>

					<!-- Properties Content (Scrollable) -->
					<div class="flex-1 overflow-y-auto flex flex-col min-h-0">
						<div 
							ref="propertiesContainer"
							:class="[
								'flex-none min-w-0 transition-opacity duration-200',
								!isMobile && propertiesCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'
							]"
						>
							<!-- Content is injected here by bpmn-js-properties-panel -->
						</div>

						<!-- ── Embedded Comment Section (shown when comment panel toggled while properties panel is open) ── -->
						<template v-if="showTimeline">
							<div class="border-t border-gray-200 flex-1 flex flex-col min-h-[300px]">
								<!-- Comment Section Header with filters -->
								<div class="flex items-center justify-between px-4 py-2.5 bg-white border-b border-gray-200 shrink-0">
									<h3 class="text-[11px] font-bold text-gray-700 uppercase tracking-wider flex items-center gap-1.5">
									<Icon icon="lucide:message-square" class="w-3.5 h-3.5" />
									Comments
									<span v-if="comments.length > 0" class="ml-0.5 px-1 py-0.5 bg-blue-100 text-blue-700 text-[9px] font-bold rounded-full">{{ comments.length }}</span>
								</h3>
								<div class="flex items-center gap-1 bg-white border border-gray-200 p-0.5 rounded-md shadow-sm">
									<button
										@click="timelineTaskFilter = !timelineTaskFilter; if (timelineTaskFilter) timelineAssignedFilter = false;"
										class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight"
										:class="timelineTaskFilter ? 'bg-orange-100 text-orange-700' : 'text-gray-400 hover:text-gray-600'"
										title="Show open tasks only"
									>
										<Icon :icon="timelineTaskFilter ? 'lucide:check-circle' : 'lucide:circle'" class="w-3 h-3" />
										Tasks
									</button>
									<button
										@click="timelineAssignedFilter = !timelineAssignedFilter; if (timelineAssignedFilter) { timelineTaskFilter = false; timelineFilterMode = 'all'; }"
										class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight"
										:class="timelineAssignedFilter ? 'bg-blue-100 text-blue-700' : 'text-gray-400 hover:text-gray-600'"
										title="Show only assigned to me"
									>
										<Icon icon="lucide:user" class="w-3 h-3" />
										Mine
									</button>
									<button
										v-if="selectedElements.length > 0"
										@click="timelineFilterMode = timelineFilterMode === 'element' ? 'all' : 'element'"
										class="flex items-center gap-1 px-2 py-0.5 rounded transition-colors text-[9px] font-bold uppercase tracking-tight max-w-[80px]"
										:class="timelineFilterMode === 'element' ? 'bg-violet-100 text-violet-700' : 'text-gray-400 hover:text-gray-600'"
										:title="`Filter by: ${selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Selected'}`"
									>
										<Icon icon="lucide:crosshair" class="w-3 h-3 shrink-0" />
										<span class="truncate">{{ selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Shape' }}</span>
									</button>
								</div>
							</div>

							<!-- Comment Input -->
							<div class="p-3 border-b border-gray-100 bg-white shrink-0">
								<div class="relative">
									<textarea
										v-model="timelineText"
										@input="handleTimelineCommentInput"
										placeholder="Add a comment..."
										class="timeline-textarea w-full px-3 py-2 text-xs border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[52px] resize-none overflow-hidden pr-10 bg-gray-50/30 leading-relaxed"
										:class="{ 'pb-10': timelineMentionedUsers.length > 0 }"
										@keydown.enter.meta.prevent="submitTimelineComment"
										@keydown.enter.ctrl.prevent="submitTimelineComment"
									></textarea>
									<div class="absolute right-2 bottom-2 flex items-center gap-1.5">
										<button
											@click="timelineIsTask = !timelineIsTask"
											class="p-1 rounded-md transition-colors"
											:class="timelineIsTask ? 'bg-orange-100 text-orange-600' : 'text-gray-400 hover:bg-gray-100'"
											title="Mark as Task"
										>
											<Icon :icon="timelineIsTask ? 'lucide:check-square' : 'lucide:square'" class="w-3.5 h-3.5" />
										</button>
										<button
											@click="submitTimelineComment"
											:disabled="!timelineText.trim()"
											class="p-1 rounded-md text-blue-600 hover:bg-blue-50 disabled:opacity-30 transition-colors"
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
											@click="selectMention(u)"
											class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
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
											<option v-for="u in timelineMentionedUsers" :key="u.value" :value="u.value">{{ u.label }}</option>
										</select>
										<span v-else class="max-w-[100px] truncate pr-2">{{ timelineMentionedUsers[0]?.label }}</span>
										<button @click="timelineAssignedTo = ''; timelineMentionedUsers = []" class="ml-0.5 p-0.5 hover:bg-blue-100 rounded-full text-blue-400 hover:text-blue-600">
											<Icon icon="lucide:x" class="w-2.5 h-2.5" />
										</button>
									</div>
								</div>
							</div>

							<!-- Comment List -->
							<div class="flex-1 overflow-y-auto p-3 space-y-4">
								<div v-if="currentElementComments.length === 0" class="flex flex-col items-center justify-center py-6 text-gray-400">
									<Icon icon="lucide:message-square" class="w-6 h-6 opacity-20 mb-1" />
									<p class="text-[11px]">No comments yet</p>
								</div>
								<div
									v-for="(c, idx) in sortedTimelineComments"
									:key="c.name"
									@click="navigateToElementComments(c.element_id)"
									class="relative pl-7 group transition-colors rounded-md p-1 -mx-1"
									:class="c.element_id && c.element_id !== 'process' ? 'cursor-pointer hover:bg-gray-50' : ''"
								>
									<div v-if="idx < sortedTimelineComments.length - 1" class="absolute left-[4px] top-[12px] bottom-[-16px] w-0.5 bg-gray-100"></div>
									<div class="absolute left-0 top-[4px] w-5 h-5 rounded-full border-2 border-white shadow-sm z-10 flex items-center justify-center overflow-hidden">
										<img v-if="c.owner_image" :src="c.owner_image" class="w-full h-full object-cover" />
										<div v-else :class="['w-full h-full flex items-center justify-center text-[7px] font-bold text-white', getAvatarColor(c.owner)]">
											{{ getInitials(c.owner_full_name || c.owner || c.author) }}
										</div>
									</div>
									<div class="space-y-1">
										<div class="flex items-center justify-between">
											<div class="flex items-center gap-1.5">
												<span class="text-[11px] font-bold text-gray-900">{{ c.owner_full_name || c.owner || c.author }}</span>
												<span v-if="c.is_task" class="px-1 py-0.5 rounded bg-orange-100 text-orange-700 text-[8px] font-bold uppercase">Task</span>
												<span v-if="timelineFilterMode === 'all' && c.element_id && c.element_id !== 'process'" class="px-1 py-0.5 rounded bg-gray-100 text-gray-500 text-[8px] font-medium">@{{ c.element_id }}</span>
											</div>
											<span class="text-[9px] text-gray-400">{{ formatCommentDate(c.creation) }}</span>
										</div>
										<p class="text-[11px] text-gray-600 leading-relaxed whitespace-pre-wrap">{{ c.comment }}</p>
										<div v-if="c.is_task && c.status" class="flex items-center justify-between pt-0.5">
											<div class="flex items-center gap-1.5">
												<Badge :label="c.status" :theme="c.status === 'Open' ? 'orange' : 'green'" size="sm" class="!text-[8px] !px-1" />
												<span v-if="c.assigned_to" class="text-[9px] text-gray-500">assigned to {{ c.assigned_to_full_name || c.assigned_to }}</span>
											</div>
											<button 
												v-if="c.status === 'Open'" 
												@click.stop="resolveComment(c)"
												class="text-[9px] font-medium text-green-600 hover:bg-green-50 px-1.5 py-0.5 rounded transition-colors"
											>
												Resolve
											</button>
										</div>
									</div>
								</div>
							</div>
						</div>
					</template>
					</div> <!-- Closes flex-1 overflow-y-auto -->
				</div>
			</transition>

			<!-- ── Standalone Comment Panel (only when properties panel is closed or collapsed) ── -->
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
					<div class="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50/50 shrink-0">
						<h3 class="text-sm font-semibold text-gray-900 flex items-center gap-2">
							<Icon icon="lucide:message-square" class="w-4 h-4 text-gray-500" />
							Comments
							<span v-if="comments.length > 0" class="ml-1 px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-bold rounded-full">{{ comments.length }}</span>
						</h3>
						<div class="flex items-center gap-1">
							<!-- Filters -->
							<div class="flex items-center gap-1 bg-white border border-gray-200 p-0.5 rounded-md shadow-sm mr-1">
								<button
									@click="timelineTaskFilter = !timelineTaskFilter; if (timelineTaskFilter) timelineAssignedFilter = false;"
									class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight"
									:class="timelineTaskFilter ? 'bg-orange-100 text-orange-700' : 'text-gray-400 hover:text-gray-600'"
									title="Show open tasks only"
								>
									<Icon :icon="timelineTaskFilter ? 'lucide:check-circle' : 'lucide:circle'" class="w-3 h-3" />
									Tasks
								</button>
								<button
									@click="timelineAssignedFilter = !timelineAssignedFilter; if (timelineAssignedFilter) { timelineTaskFilter = false; timelineFilterMode = 'all'; }"
									class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight"
									:class="timelineAssignedFilter ? 'bg-blue-100 text-blue-700' : 'text-gray-400 hover:text-gray-600'"
									title="Show only assigned to me"
								>
									<Icon icon="lucide:user" class="w-3 h-3" />
									Mine
								</button>
								<!-- Shape filter pill: shows when an element is selected -->
								<button
									v-if="selectedElements.length > 0"
									@click="timelineFilterMode = timelineFilterMode === 'element' ? 'all' : 'element'"
									class="flex items-center gap-1 px-2 py-0.5 rounded transition-all text-[9px] font-bold uppercase tracking-tight max-w-[80px]"
									:class="timelineFilterMode === 'element' ? 'bg-violet-100 text-violet-700' : 'text-gray-400 hover:text-gray-600'"
									:title="`Filter by: ${selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Selected'}`"
								>
									<Icon icon="lucide:crosshair" class="w-3 h-3 shrink-0" />
									<span class="truncate">{{ selectedElements[0]?.businessObject?.name || selectedElements[0]?.id || 'Shape' }}</span>
								</button>
							</div>
							<button
								@click="showTimeline = false"
								class="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors"
								title="Close"
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
								@input="handleTimelineCommentInput"
								placeholder="Add a comment..."
								class="timeline-textarea w-full px-3 py-2 text-xs border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-400 focus:outline-none min-h-[60px] resize-none overflow-hidden pr-10 bg-gray-50/30 leading-relaxed"
								:class="{ 'pb-10': timelineMentionedUsers.length > 0 }"
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
									@click="selectMention(u)"
									class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 flex items-center justify-between"
								>
									<span>{{ u.label }}</span>
								</div>
							</div>

							<!-- Quick Comment Actions -->
							<div class="absolute right-2 bottom-2 flex items-center gap-1.5">
								<button
									@click="timelineIsTask = !timelineIsTask"
									class="p-1 rounded-md transition-colors"
									:class="timelineIsTask ? 'bg-orange-100 text-orange-600' : 'text-gray-400 hover:bg-gray-100'"
									title="Mark as Task"
								>
									<Icon :icon="timelineIsTask ? 'lucide:check-square' : 'lucide:square'" class="w-4 h-4" />
								</button>
								<button
									@click="submitTimelineComment"
									:disabled="!timelineText.trim()"
									class="p-1 rounded-md text-blue-600 hover:bg-blue-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
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
									<option v-for="u in timelineMentionedUsers" :key="u.value" :value="u.value">{{ u.label }}</option>
								</select>
								<span v-else class="max-w-[100px] truncate pr-2">{{ timelineMentionedUsers[0]?.label }}</span>
								<button @click="timelineAssignedTo = ''; timelineMentionedUsers = []" class="ml-0.5 p-0.5 hover:bg-blue-100 rounded-full text-blue-400 hover:text-blue-600">
									<Icon icon="lucide:x" class="w-2.5 h-2.5" />
								</button>
							</div>
						</div>
						<div class="mt-1 flex items-center justify-between px-1">
							<span class="text-[9px] text-gray-400 flex items-center gap-1">
								<Icon icon="lucide:command" class="w-2.5 h-2.5" />
								+ Enter to post
							</span>
							<span v-if="timelineIsTask" class="text-[9px] font-bold text-orange-500 uppercase tracking-tighter">Creating Task</span>
						</div>
					</div>

					<!-- Comment List -->
					<div class="flex-1 overflow-y-auto p-4 space-y-6">
						<div v-if="currentElementComments.length === 0" class="flex flex-col items-center justify-center py-10 text-gray-400">
							<Icon icon="lucide:message-square" class="w-8 h-8 opacity-20 mb-2" />
							<p class="text-xs">No comments yet</p>
						</div>

						<div
							v-for="(c, idx) in sortedTimelineComments"
							:key="c.name"
							@click="navigateToElementComments(c.element_id)"
							class="relative pl-8 group transition-colors rounded-md p-1.5 -mx-1.5"
							:class="c.element_id && c.element_id !== 'process' ? 'cursor-pointer hover:bg-gray-50' : ''"
						>
							<!-- Vertical Line -->
							<div
								v-if="idx < sortedTimelineComments.length - 1"
								class="absolute left-[5px] top-[14px] bottom-[-24px] w-0.5 bg-gray-100"
							></div>

							<!-- Avatar -->
							<div class="absolute left-0 top-[6px] w-6.5 h-6.5 rounded-full border-2 border-white shadow-sm z-10 flex items-center justify-center overflow-hidden -translate-x-1">
								<img
									v-if="c.owner_image"
									:src="c.owner_image"
									class="w-full h-full object-cover"
								/>
								<div
									v-else
									:class="['w-full h-full flex items-center justify-center text-[8px] font-bold text-white', getAvatarColor(c.owner)]"
								>
									{{ getInitials(c.owner_full_name || c.owner || c.author) }}
								</div>
							</div>

							<div class="space-y-1.5">
								<div class="flex items-center justify-between">
									<div class="flex items-center gap-2">
										<span class="text-xs font-bold text-gray-900">{{ c.owner_full_name || c.owner || c.author }}</span>
										<span v-if="c.is_task" class="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 text-[9px] font-bold uppercase">Task</span>
										<span v-if="timelineFilterMode === 'all' && c.element_id && c.element_id !== 'process'" class="px-1 py-0.5 rounded bg-gray-100 text-gray-500 text-[8px] font-medium">@{{ c.element_id }}</span>
									</div>
									<span class="text-[10px] text-gray-400 font-medium">{{ formatCommentDate(c.creation) }}</span>
								</div>
								<p class="text-xs text-gray-600 leading-relaxed whitespace-pre-wrap">{{ c.comment }}</p>

								<!-- Task status -->
								<div v-if="c.is_task && c.status" class="flex items-center justify-between pt-1">
									<div class="flex items-center gap-2">
										<Badge
											:label="c.status"
											:theme="c.status === 'Open' ? 'orange' : 'green'"
											size="sm"
											class="!text-[9px] !px-1.5"
										/>
										<span v-if="c.assigned_to" class="text-[10px] text-gray-500">assigned to {{ c.assigned_to_full_name || c.assigned_to }}</span>
									</div>
									<button 
										v-if="c.status === 'Open'" 
										@click.stop="resolveComment(c)"
										class="text-[10px] font-medium text-green-600 hover:bg-green-50 px-2 py-0.5 rounded transition-colors"
									>
										Resolve
									</button>
								</div>
							</div>
						</div>
					</div>
				</div>
			</transition>

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
							@input="handleCommentInput"
							@keydown.enter.meta.prevent="submitComment"
							@keydown.enter.ctrl.prevent="submitComment"
							:required="true"
							placeholder="What's on your mind?"
							class="main-comment-textarea"
						/>
						<div
							v-if="showMentionDropdown && activeMentionContext === 'dialog'"
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
						
						<div v-if="comment.is_task && comment.status" class="flex items-center justify-between pt-2 border-t border-gray-50 mt-2">
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
			data-context-menu
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

		<!-- Message name dialog -->
		<Dialog
			v-model="messageDialog.show"
			:options="{
				title: messageDialog.isEdit ? 'Edit Message' : 'New Message',
				size: 'sm',
				actions: [
					{
						label: messageDialog.isEdit ? 'Save' : 'Create',
						variant: 'solid',
						disabled: !messageDialog.name?.trim(),
						onClick: ({ close }) => onMessageDialogSave(close),
					},
				],
			}"
		>
			<template #body-content>
				<div class="space-y-4">
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">Message Name</label>
						<input
							v-model="messageDialog.name"
							type="text"
							placeholder="e.g. GitHub: PR Merged"
							class="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
							@keydown.enter="messageDialog.name?.trim() && onMessageDialogSave(() => messageDialog.show = false)"
						/>
						<p class="mt-1 text-xs text-gray-500">The name must match what the external system sends.</p>
					</div>
				</div>
			</template>
		</Dialog>

		<!-- AI Agent Task config modal -->
		<AIAgentConfigModal
			v-if="aiAgentModal.show && aiAgentModal.element"
			:element="aiAgentModal.element"
			:modeler="modeler"
			@close="aiAgentModal.show = false"
		/>
	</div>
</template>

<script setup>
import { ref, shallowRef, markRaw, onMounted, onBeforeUnmount, onUnmounted, watch, computed, nextTick } from "vue";
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

import FormattingToolbar from "@/components/FormattingToolbar.vue";
import ProsAllyPanel from "@/components/ProsAllyPanel.vue";
import AIAgentConfigModal from "@/components/AIAgentConfigModal.vue";
import { layoutBpmnXml } from "@/utils/bpmnLayout.js";
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
import { customTextStyleModule, stickyNoteModule, serviceTaskIconModule } from "@/renderers";

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
import aiAgentPropertiesProviderModule from "@/bpmn/aiAgentPropertiesProvider";
import aiAgentReplaceMenuProviderModule from "@/bpmn/aiAgentReplaceMenuProvider";
import aiAgentRendererModule from "@/bpmn/aiAgentRenderer";

import scriptTaskPropertiesProviderModule from "@/bpmn/scriptTaskPropertiesProvider";
import businessRuleTaskPropertiesProviderModule from "@/bpmn/businessRuleTaskPropertiesProvider";
import timerPropertiesProviderModule from "@/bpmn/timerPropertiesProvider";
import startEventPropertiesProviderModule from "@/bpmn/startEventPropertiesProvider";
import conditionalStartEventPropertiesProviderModule from "@/bpmn/conditionalStartEventPropertiesProvider";
import lanePropertiesProviderModule from "@/bpmn/lanePropertiesProvider";
import propertiesPanelFilterModule from "@/bpmn/propertiesPanelFilter";
import commentContextPadModule from "@/bpmn/commentContextPad";
import { encodeHtmlAttr, decodeHtmlAttr } from "@/bpmn/shared/htmlAttrCodec";

// bpmnlint — diagram validation
import lintModule from "bpmn-js-bpmnlint";
import "bpmn-js-bpmnlint/dist/assets/css/bpmn-js-bpmnlint.css";
import bpmnlintConfig from "@/linting/bpmnlintrc.js";

// Import bpmn-js CSS
import "bpmn-js/dist/assets/diagram-js.css";
import "bpmn-js/dist/assets/bpmn-js.css";
import "bpmn-js/dist/assets/bpmn-font/css/bpmn.css";

// Touch interaction support for mobile devices
import touchInteractionModule from "bpmn-js-touch-interaction";

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
	"confirm-script-delete",
	"launch-markdown-editor",
	"launch-callactivity-editor",
	"launch-callactivity-search",
	"launch-notification-editor",
	"launch-dmn-editor",
	"launch-notify-assignee-editor",
]);

// Commenting state
const comments = ref([]);
const timelineText = ref("");
const showTimeline = ref(false);
const timelineFilterMode = ref("element"); // 'element' or 'all'
const timelineTaskFilter = ref(false);
const timelineAssignedFilter = ref(false);
const timelineCollapsed = ref(false);
const showCommentDialog = ref(false);
const showViewCommentsDialog = ref(false);
const activeCommentElement = ref(null);
const selectedElementComments = ref([]);
const messageDialog = ref({
	show: false,
	isEdit: false,
	name: "",
	elementId: "",
	_eventBus: null,
});
const aiAgentModal = ref({ show: false, element: null });
const isCommentMode = ref(false);
const commentFormData = ref({
	text: "",
	assigned_to: "",
	is_task: false
});
const users = ref([]);

// Inline Comment Popover state
const showInlineCommentPopover = ref(false);
const inlineCommentPopoverEl = ref(null);
const inlineCommentFormData = ref({
	text: "",
	assigned_to: "",
	is_task: false
});
const inlineMentionedUsers = ref([]);
const inlineCommentElement = ref(null);
const inlineCommentOverlayTarget = ref(null);

function toggleTimeline(mode = "all") {
	if (showTimeline.value && timelineFilterMode.value === mode) {
		showTimeline.value = false;
		return;
	}
	showTimeline.value = true;
	timelineFilterMode.value = mode;
	if (mode === "all" && modelerInstance.value) {
		modelerInstance.value.get("selection").select([]);
	}
}

function navigateToElementComments(elementId) {
	if (!elementId || elementId === "process" || !modelerInstance.value) return;
	
	const elementRegistry = modelerInstance.value.get("elementRegistry");
	const element = elementRegistry.get(elementId);
	
	if (element) {
		const selection = modelerInstance.value.get("selection");
		selection.select(element);
		
		// Ensure timeline shows comments for this element
		timelineFilterMode.value = "element";
		
		// Scroll to the element
		const canvas = modelerInstance.value.get("canvas");
		canvas.scrollToElement(element);
	}
}

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
	toggleTimeline
});

const processNameForPanel = computed(() =>
	internalProcessName.value || props.modelName || ""
);

const currentElementComments = computed(() => {
	let filtered = [];
	if (timelineFilterMode.value === "all") {
		filtered = comments.value;
	} else {
		const element = selectedElements.value[0];
		const id = element?.id || "process";
		filtered = comments.value.filter(c => (c.element_id || "process") === id);
	}
	
	if (timelineTaskFilter.value) {
		filtered = filtered.filter(c => c.is_task && c.status === "Open");
	}
	
	if (timelineAssignedFilter.value) {
		const currentUser = window.frappe?.boot?.session_user || window.frappe?.session?.user || window.frappe?.boot?.user?.name || window.frappe?.user_name || window.frappe?.user?.name;
		filtered = filtered.filter(c => {
			// Basic guards
			if (!c.is_task || !currentUser) return false;
			
			// Case-insensitive status check
			const status = String(c.status || "").toLowerCase().trim();
			if (status !== "open") return false;
			
			// Normalize all available identity strings
			const assigneeId = String(c.assigned_to || "").toLowerCase().trim();
			const assigneeName = String(c.assigned_to_full_name || "").toLowerCase().trim();
			const currentUserId = String(currentUser || "").toLowerCase().trim();
			const currentUserFull = String(window.frappe?.boot?.user?.full_name || "").toLowerCase().trim();
			
			// 1. Direct ID match (c.akeru@one-fm.com === c.akeru@one-fm.com)
			if (assigneeId === currentUserId) return true;
			
			// 2. Name to Name match (Chukwuebuka Akeru === Chukwuebuka Akeru)
			if (assigneeName && currentUserFull && assigneeName === currentUserFull) return true;
			
			// 3. ID to Name cross-match (Chukwuebuka Akeru === Chukwuebuka Akeru, when one is used as ID)
			if (assigneeId && currentUserFull && assigneeId === currentUserFull) return true;
			
			// 4. Name to ID cross-match (Chukwuebuka Akeru === Chukwuebuka Akeru, when other is used as ID)
			if (assigneeName && currentUserId && assigneeName === currentUserId) return true;
			
			return false;
		});
	}
	
	return filtered;
});

const sortedTimelineComments = computed(() => {
	return [...currentElementComments.value].sort((a, b) => new Date(b.creation) - new Date(a.creation));
});

function formatCommentDate(dateStr) {
	if (!dateStr) return "";
	const d = new Date(dateStr);
	const day = String(d.getDate()).padStart(2, '0');
	const month = String(d.getMonth() + 1).padStart(2, '0');
	const year = d.getFullYear();
	const hours = String(d.getHours()).padStart(2, '0');
	const minutes = String(d.getMinutes()).padStart(2, '0');
	const seconds = String(d.getSeconds()).padStart(2, '0');
	return `${day}/${month}/${year}, ${hours}:${minutes}:${seconds}`;
}

async function submitTimelineComment() {
	if (!timelineText.value.trim() || !props.modelName) return;
	
	const element = selectedElements.value[0];
	const elementId = element?.id || "process";
	
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
			params: {
				model_name: props.modelName,
				element_id: elementId,
				comment: timelineText.value.trim(),
				assigned_to: timelineAssignedTo.value,
				is_task: timelineIsTask.value ? 1 : 0
			}
		});
		timelineText.value = "";
		timelineAssignedTo.value = "";
		timelineIsTask.value = false;
		timelineMentionedUsers.value = [];
		fetchComments();
	} catch (err) {
		console.error("Failed to post timeline comment:", err);
	}
}

function autoResizeTextarea(el) {
	if (!el) return;
	el.style.height = 'auto';
	el.style.height = (el.scrollHeight) + 'px';
}

function handleTimelineCommentInput(e) {
	if (!e || !e.target || typeof e.target.selectionStart !== 'number') return;
	
	const text = timelineText.value || "";
	
	// Sync mentioned users
	if (!text) {
		timelineMentionedUsers.value = [];
		timelineAssignedTo.value = "";
		timelineIsTask.value = false;
	} else {
		const currentUsers = timelineMentionedUsers.value.filter(u => text.includes("@" + u.label));
		if (currentUsers.length !== timelineMentionedUsers.value.length) {
			timelineMentionedUsers.value = currentUsers;
			if (!currentUsers.some(u => u.value === timelineAssignedTo.value)) {
				timelineAssignedTo.value = currentUsers.length > 0 ? currentUsers[0].value : "";
				if (currentUsers.length === 0) {
					timelineIsTask.value = false;
				}
			}
		}
	}
	
	const cursorPosition = e.target.selectionStart;
	const textBeforeCursor = text.substring(0, cursorPosition);
	const match = textBeforeCursor.match(/@([^\s]{0,30})$/);
	
	if (match) {
		showMentionDropdown.value = true;
		mentionSearchQuery.value = match[1];
		mentionStartIndex.value = cursorPosition - match[1].length - 1;
		activeMentionContext.value = "timeline";
	} else {
		showMentionDropdown.value = false;
	}

	// Auto-resize textarea
	nextTick(() => autoResizeTextarea(e.target));
}

const timelineAssignedTo = ref("");
const timelineIsTask = ref(false);
const timelineMentionedUsers = ref([]);

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
const activeMentionContext = ref("");
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
// Desktop: start visible (collapsed sidebar); Mobile: start hidden (no bottom sheet on load)
const showPropertiesPanel = ref(window.innerWidth >= 640);
const propertiesCollapsed = ref(true);
const isMounted = ref(false);
const isImporting = ref(false);
// const showMinimap = ref(true); // DISABLED
const selectedElements = shallowRef([]);
const modelerInstance = shallowRef(null);

// Mobile responsiveness
const { isMobile } = useWindowSize();
const showMobileFormatPopover = ref(false);
const showProsAllyPanel = ref(false);
const internalProcessName = ref("");
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

// Empty BPMN diagram template — generates a unique process ID each time
function makeEmptyDiagram() {
	const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)), b => b.toString(16).padStart(2, "0")).join("");
	const processId = `Process_${hex}`;
	return `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="${processId}" isExecutable="false" />
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${processId}" />
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;
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
						{ name: "notifyAssignee",        isAttr: true, type: "String" },
						{ name: "notifyAssigneeBody",    isAttr: true, type: "String" },
						{ name: "notifyAssigneeSubject", isAttr: true, type: "String" },
						{ name: "notifyAssigneeTemplate", isAttr: true, type: "String" }
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
						{ name: "updateFieldValue",     isAttr: true, type: "String" },
						// Multi-row field update (JSON array of {field, value})
						{ name: "updateFieldRows",      isAttr: true, type: "String" },
						// Google Chat attrs
						{ name: "gchatType",            isAttr: true, type: "String" },
						{ name: "gchatEmail",           isAttr: true, type: "String" },
						{ name: "gchatSpaceId",         isAttr: true, type: "String" },
						{ name: "gchatMessage",         isAttr: true, type: "String" },
						// Push Notification attrs
						{ name: "pushDoctype",          isAttr: true, type: "String" },
						{ name: "pushTitle",            isAttr: true, type: "String" },
						{ name: "pushMessage",          isAttr: true, type: "String" },
						{ name: "pushToUsers",          isAttr: true, type: "String" },
						{ name: "pushToDocFields",      isAttr: true, type: "String" },
						{ name: "pushToRoles",          isAttr: true, type: "String" },
						// AI Agent Task attrs
						{ name: "aiBackend",            isAttr: true, type: "String" },
						{ name: "aiProvider",           isAttr: true, type: "String" },
						{ name: "aiModel",              isAttr: true, type: "String" },
						{ name: "aiOutputVariable",     isAttr: true, type: "String" },
						{ name: "aiSystemPrompt",       isAttr: true, type: "String" },
						{ name: "aiUserPrompt",         isAttr: true, type: "String" },
						{ name: "aiResponseFormat",     isAttr: true, type: "String" },
						{ name: "aiResponseSchema",     isAttr: true, type: "String" },
						{ name: "aiTemperature",        isAttr: true, type: "String" },
						{ name: "aiTopP",               isAttr: true, type: "String" },
						{ name: "aiMaxTokens",          isAttr: true, type: "String" },
						{ name: "aiTimeout",            isAttr: true, type: "String" },
						{ name: "aiMaxRetries",         isAttr: true, type: "String" },
						{ name: "aiWriteBackField",     isAttr: true, type: "String" }
						]
				});
			}

			// Business Rule Task decision reference extension
			const hasBusinessRuleTaskExt = spiffModdleExtension.types.find(t => t.name === "BusinessRuleTaskDecisionExtension");
			if (!hasBusinessRuleTaskExt) {
				spiffModdleExtension.types.push({
					name: "BusinessRuleTaskDecisionExtension",
					extends: ["bpmn:BusinessRuleTask"],
					properties: [
						{ name: "calledDecisionId", isAttr: true, type: "String" }
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
				aiAgentPropertiesProviderModule,
				aiAgentReplaceMenuProviderModule,
				aiAgentRendererModule,

				scriptTaskPropertiesProviderModule,
				businessRuleTaskPropertiesProviderModule,
				timerPropertiesProviderModule,
				startEventPropertiesProviderModule,
				conditionalStartEventPropertiesProviderModule,
				lanePropertiesProviderModule,
				// minimapModule, // DISABLED
				translateModule,
				customTextStyleModule,
				resizeModule,
				stickyNoteModule,
				serviceTaskIconModule,
				clipboardModule,
				lintModule,
				nativeCopyPasteModule,
				touchInteractionModule,
				propertiesPanelFilterModule,
				commentContextPadModule,
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
			// In bpmn-js v18+, keyboard binds to the canvas automatically.
			// Disable keyboard entirely in readonly mode.
			keyboard: props.readonly ? false : {},
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

			// Intercept modeling.removeElements so ALL deletion paths trigger the
			// script-delete confirmation (context pad, keyboard, toolbar).
			if (!props.readonly) {
				const modeling = modeler.get("modeling");
				const origRemoveElements = modeling.removeElements.bind(modeling);
				modeling.removeElements = function(elements) {
					if (!Array.isArray(elements) || elements.length === 0) {
						return origRemoveElements(elements);
					}
					const scriptNames = getLinkedScriptNames(elements);
					if (scriptNames.length > 0) {
						const usageMap = countScriptUsageAcrossCanvas(scriptNames);
						emit("confirm-script-delete", {
							elements,
							scriptNames,
							usageMap,
							doDelete: origRemoveElements,
						});
						return;
					}
					return origRemoveElements(elements);
				};
			}


			const linting = modeler.get("linting");
			if (linting) {
				const originalFormatIssues = linting._formatIssues;
				linting._formatIssues = function (issues) {
					let formattedIssues = originalFormatIssues.call(this, issues);

					try {
						const canvas = modeler.get("canvas");
						const rootElement = canvas.getRootElement();

						// Suppress all lint issues on an empty canvas (no shapes).
						// Rules like start-event-required / end-event-required fire
						// on the bare process element, producing false positives for
						// a blank diagram that the user has not started drawing on.
						const rootBo = rootElement.businessObject;
						const flowEls = rootBo && (rootBo.flowElements || []);
						if (!flowEls.length) {
							return {};
						}

						// Helper to collect all element IDs strictly contained within the given moddle object
						const getModdleDescendants = (bo, descendants = new Set(), visited = new Set()) => {
							if (!bo || typeof bo !== "object") return descendants;
							if (visited.has(bo)) return descendants;
							visited.add(bo);

							if (bo.id) descendants.add(bo.id);

							const containmentKeys = [
								"flowElements", "laneSets", "lanes", "artifacts", "eventDefinitions",
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
					} catch (err) {
						console.warn("[bpmnlint] _formatIssues filter failed, returning unfiltered issues:", err);
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

			// Cleanup comments and ToDos when an element is deleted
			eventBus.on("commandStack.elements.delete.postExecute", (e) => {
				const elements = e.context.elements || [];
				elements.forEach(element => {
					if (element.id && props.modelName) {
						frappeRequest({
							url: "/api/method/one_bpmn.api.canvas_comments.delete_canvas_element_assets",
							params: {
								model_name: props.modelName,
								element_id: element.id
							}
						}).then(() => {
							// Refresh comments to reflect deletion
							fetchComments();
						});
					}
				});
			});


			// Listen for selection changes for formatting toolbar
			eventBus.on("selection.changed", (e) => {
				selectedElements.value = e.newSelection || [];

				// Auto-open the properties panel when an element is selected
				if (e.newSelection?.length > 0) {
					showPropertiesPanel.value = true;
					timelineFilterMode.value = "element";
					if (!isMobile.value) {
						propertiesCollapsed.value = false;
					}
				}

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

				// Only allow comments on actual shapes — skip the root process element
				if (!element.parent) return;

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

			// Canvas clicks (empty area) — intentionally ignored for commenting.
			// Comments must be associated with a shape, not the canvas.

			// Right-click context menu — delegates to composable
			registerContextMenuListeners(eventBus);

			// Listen for inline comment request from context pad
			eventBus.on("commentContextPad.addComment", ({ element }) => {
				openInlineComment(element);
			});

			// Global click listener for closing inline popover/dropdowns
			const handleGlobalClick = (e) => {
				if (!showInlineCommentPopover.value) return;

				const target = e.target;
				const popover = inlineCommentPopoverEl.value;
				const isInsidePopover = popover?.contains(target);

				// Close user dropdown if click is outside the assignment input area
				const isInsideUserSearch = target.closest('.user-search-container');
				if (!isInsideUserSearch) {
					showUserDropdown.value = false;
				}

				// Close mention dropdown if click is outside the textarea area
				const isInsideTextArea = target.closest('textarea');
				const isInsideMentions = target.closest('.mentions-container');
				if (!isInsideTextArea && !isInsideMentions) {
					showMentionDropdown.value = false;
				}

				// Close popover if clicked outside and empty
				if (!isInsidePopover && !inlineCommentFormData.value.text) {
					closeInlineComment(true);
				}
			};
			document.addEventListener("mousedown", handleGlobalClick);

			onUnmounted(() => {
				document.removeEventListener("mousedown", handleGlobalClick);
			});

			// Re-inject only when calledElement actually changed
			// churn and repeated network requests on every command stack event.
			eventBus.on("commandStack.changed", () => {
				updateUndoRedoState();
				const selection = modeler.get("selection");
				const selected = selection.get();
				if (selected?.length === 1 && selected[0]?.type === "bpmn:CallActivity") {
					reinjectIfCalledElementChanged(selected[0], propertiesContainer);
				}
				// Force properties panel to refresh and update dynamic properties (like Service Task fields)
				try {
					eventBus.fire("propertiesPanel.providersChanged");
				} catch (e) {
					console.warn("Failed to fire propertiesPanel.providersChanged:", e);
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

			eventBus.on("spiff.dmn.edit", (event) => {
				// SpiffExtensionLaunchButton fires { value, eventBus } — it does NOT
				// include the element. Resolve it from the modeler's selection.
				const selection = modeler.get("selection");
				const selected = selection.get();
				const element = selected?.length === 1 ? selected[0] : null;
				emit("launch-dmn-editor", {
					element,
					value: event.value || "",
					eventBus: event.eventBus,
				});
			});

			// AI Agent Task config modal
			eventBus.on("launch-ai-agent-editor", (event) => {
				aiAgentModal.value = { show: true, element: markRaw(event.element) };
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

			// Notify Assignee editor (User Tasks)
			eventBus.on("spiff.userTask.notifyAssignee.edit", (event) => {
				emit("launch-notify-assignee-editor", {
					element: event.element,
					body: decodeHtmlAttr(event.body) || "",
					subject: event.subject || "",
					template: event.template || "",
					eventBus: event.eventBus,
				});
			});

			// Write notify-assignee HTML body + subject + template back to BPMN element
			eventBus.on("spiff.userTask.notifyAssignee.update", (event) => {
				if (event.element) {
					const modeling = modeler.get("modeling");
					const bo = event.element.businessObject || event.element;
					modeling.updateModdleProperties(event.element, bo, {
						"spiffworkflow:notifyAssigneeBody": encodeHtmlAttr(event.body),
						"spiffworkflow:notifyAssigneeSubject": event.subject || undefined,
						"spiffworkflow:notifyAssigneeTemplate": event.template || undefined,
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

			eventBus.on("spiff.dmn_files.requested", async (event) => {
				let options = [];
				if (props.modelName) {
					try {
						const resp = await frappeRequest({
							url: "/api/method/one_bpmn.api.dmn_api.get_decision_list",
							params: { process_model: props.modelName },
						});
						// frappeRequest auto-unwraps "message"; resp is the list directly
						const decisions = Array.isArray(resp) ? resp : (resp?.message || []);
						options = decisions.map((d) => ({
							label: d.decision_name || d.decision_id,
							value: d.decision_id,
						}));
					} catch (err) {
						console.warn("[BpmnEditor] Failed to fetch DMN files:", err);
					}
				}
				event.eventBus.fire("spiff.dmn_files.returned", { options });
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
				// Read existing <bpmn:message> elements from the definitions
				const definitions = modeler.getDefinitions();
				const rootElements = definitions?.rootElements || [];
				const messages = rootElements
					.filter((el) => el.$type === "bpmn:Message")
					.map((msg) => ({ identifier: msg.name, name: msg.name }));
				event.eventBus.fire("spiff.messages.returned", {
					configuration: { messages },
				});
			});

			// ── Message editing (IntermediateCatchEvent, ReceiveTask) ────────
			// When the BA clicks "Open message editor" on a catch event,
			// show a frappe-ui Dialog to type/edit the message name.
			// On save, fire spiff.add_message.returned which creates the
			// <bpmn:Message> element and wires it to the catch event.
			eventBus.on("spiff.message.edit", (event) => {
				messageDialog.value.isEdit = true;
				messageDialog.value.name = event.value?.messageId || "";
				messageDialog.value.elementId = event.value?.elementId || "";
				messageDialog.value._eventBus = event.eventBus;
				messageDialog.value.show = true;
			});

			// Handle "add new message" from the MessageSelect dropdown
			eventBus.on("spiff.add_message.requested", (event) => {
				messageDialog.value.isEdit = false;
				messageDialog.value.name = "";
				messageDialog.value.elementId = "";
				messageDialog.value._eventBus = event.eventBus;
				messageDialog.value.show = true;
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
			await modeler.importXML(makeEmptyDiagram());

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

function onMessageDialogSave(close) {
	const { name, elementId, _eventBus } = messageDialog.value;
	const trimmedName = name?.trim();
	if (!trimmedName || !_eventBus) return;

	_eventBus.fire("spiff.add_message.returned", {
		name: trimmedName,
		elementId: elementId,
		correlation_properties: {},
	});
	close();
}

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

function getLinkedScriptNames(elements) {
	const names = new Set();
	for (const el of elements) {
		const bo = el.businessObject;
		if (!bo) continue;
		// bpmn:ScriptTask stores the server script name in `script` field
		if (bo.$type === "bpmn:ScriptTask" && bo.script && bo.script.trim()) {
			names.add(bo.script.trim());
		}
		// Pre/PostScript stored in extensionElements
		const exts = bo.extensionElements?.get("values") || [];
		for (const ext of exts) {
			const tag = ext.$type || "";
			if ((tag === "spiffworkflow:PreScript" || tag === "spiffworkflow:PostScript") && ext.value?.trim()) {
				names.add(ext.value.trim());
			}
		}
	}
	return [...names];
}

function countScriptUsageAcrossCanvas(scriptNames) {
	if (!modeler || !scriptNames.length) return {};
	const registry = modeler.get("elementRegistry");
	const counts = Object.fromEntries(scriptNames.map((n) => [n, 0]));
	registry.forEach((el) => {
		const bo = el.businessObject;
		if (!bo) return;
		if (bo.$type === "bpmn:ScriptTask" && bo.script?.trim()) {
			if (counts[bo.script.trim()] !== undefined) counts[bo.script.trim()]++;
		}
		const exts = bo.extensionElements?.get("values") || [];
		for (const ext of exts) {
			const tag = ext.$type || "";
			if ((tag === "spiffworkflow:PreScript" || tag === "spiffworkflow:PostScript") && ext.value?.trim()) {
				if (counts[ext.value.trim()] !== undefined) counts[ext.value.trim()]++;
			}
		}
	});
	return counts;
}

function deleteSelected() {
	if (!modeler) return;
	const selection = modeler.get("selection");
	const modeling = modeler.get("modeling");
	const selected = selection.get();
	if (selected && selected.length > 0) {
		modeling.removeElements(selected); // goes through the intercept in onReady
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
		mentionStartIndex.value = cursorPosition - match[1].length - 1;
		activeMentionContext.value = "dialog";
	} else {
		showMentionDropdown.value = false;
	}

	// Auto-resize textarea
	nextTick(() => autoResizeTextarea(e.target));
}

// --- Inline Comment Handlers ---

function openInlineComment(element) {
	if (props.readonly) return;
	
	activeCommentElement.value = element;
	inlineCommentElement.value = element;
	inlineCommentFormData.value = {
		text: "",
		assigned_to: "",
		is_task: false
	};
	inlineMentionedUsers.value = [];
	userSearchQuery.value = "";
	showInlineCommentPopover.value = true;
	
	const overlays = modeler.get("overlays");
	// Remove any existing inline popover
	overlays.remove({ type: "inline-comment" });
	
	nextTick(() => {
		// Create a stable DOM target for the Teleport
		const target = document.createElement("div");
		target.className = "inline-comment-overlay-wrapper";
		
		overlays.add(element.id, "inline-comment", {
			position: {
				bottom: -20,
				right: -20
			},
			html: target,
			scale: false
		});
		
		inlineCommentOverlayTarget.value = target;
		
		// Focus textarea
		setTimeout(() => {
			if (inlineCommentPopoverEl.value) {
				const textarea = inlineCommentPopoverEl.value.querySelector("textarea");
				if (textarea) textarea.focus();
			}
		}, 50);
	});
}

function closeInlineComment(force = false) {
	if (!force && inlineCommentFormData.value.text) return;

	showInlineCommentPopover.value = false;
	inlineCommentElement.value = null;
	inlineCommentOverlayTarget.value = null; // Unmounts the Teleport content
	
	const overlays = modeler.get("overlays");
	overlays.remove({ type: "inline-comment" });
}

async function submitInlineComment() {
	if (!inlineCommentFormData.value.text || !props.modelName || !inlineCommentElement.value) return;

	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
			params: {
				model_name: props.modelName,
				element_id: inlineCommentElement.value.id,
				comment: inlineCommentFormData.value.text,
				assigned_to: inlineCommentFormData.value.assigned_to,
				is_task: inlineCommentFormData.value.is_task ? 1 : 0
			}
		});

		closeInlineComment(true);
		fetchComments();
		
		// To fix unresponsiveness, re-select the element after a short delay
		// which forces the context pad to refresh and ensures interaction is restored.
		setTimeout(() => {
			if (inlineCommentElement.value) {
				const selection = modeler.get("selection");
				selection.select(inlineCommentElement.value);
			}
		}, 100);
	} catch (err) {
		console.error("Failed to post inline comment:", err);
	}
}

function handleInlineCommentInput(e) {
	// Reusing mention logic for inline popover
	if (!e || !e.target || typeof e.target.selectionStart !== 'number') return;
	
	const text = inlineCommentFormData.value.text || "";
	
	// Sync mentioned users (checking if @user.label is still in text)
	if (!text) {
		inlineMentionedUsers.value = [];
		inlineCommentFormData.value.assigned_to = "";
		inlineCommentFormData.value.is_task = false;
	} else {
		const currentUsers = inlineMentionedUsers.value.filter(u => text.includes("@" + u.label));
		if (currentUsers.length !== inlineMentionedUsers.value.length) {
			inlineMentionedUsers.value = currentUsers;
			if (!currentUsers.some(u => u.value === inlineCommentFormData.value.assigned_to)) {
				inlineCommentFormData.value.assigned_to = currentUsers.length > 0 ? currentUsers[0].value : "";
				if (currentUsers.length === 0) {
					inlineCommentFormData.value.is_task = false;
				}
			}
		}
	}
	
	const cursorPosition = e.target.selectionStart;
	const textBeforeCursor = text.substring(0, cursorPosition);
	const match = textBeforeCursor.match(/@([^\s]{0,30})$/);
	
	if (match) {
		showMentionDropdown.value = true;
		mentionSearchQuery.value = match[1];
		mentionStartIndex.value = cursorPosition - match[1].length - 1;
		activeMentionContext.value = "inline";
	} else {
		showMentionDropdown.value = false;
	}

	// Auto-resize textarea
	nextTick(() => autoResizeTextarea(e.target));
}

function selectMention(user) {
	const isTimeline = activeMentionContext.value === "timeline";
	const isInline = activeMentionContext.value === "inline";
	const targetData = isTimeline ? timelineText : (isInline ? inlineCommentFormData : commentFormData);
	
	const text = isTimeline ? targetData.value : targetData.value.text;
	const before = text.substring(0, mentionStartIndex.value);
	const after = text.substring(mentionStartIndex.value + mentionSearchQuery.value.length + 1);
	const newText = before + "@" + user.label + " " + after;
	
	if (isTimeline) {
		timelineText.value = newText;
		if (!timelineMentionedUsers.value.some(u => u.value === user.value)) {
			timelineMentionedUsers.value.push(user);
		}
		timelineAssignedTo.value = user.value;
		// Auto-enable task mode if we mention someone in the timeline
		timelineIsTask.value = true;
	} else if (isInline) {
		inlineCommentFormData.value.text = newText;
		if (!inlineMentionedUsers.value.some(u => u.value === user.value)) {
			inlineMentionedUsers.value.push(user);
		}
		inlineCommentFormData.value.assigned_to = user.value;
		inlineCommentFormData.value.is_task = true;
	} else {
		commentFormData.value.text = newText;
	}
	
	showMentionDropdown.value = false;
	
	// Refocus textarea
	nextTick(() => {
		const selector = isTimeline ? ".timeline-textarea" : (isInline ? ".inline-comment-textarea" : ".main-comment-textarea");
		const textarea = document.querySelector(selector);
		if (textarea) textarea.focus();
	});
}

async function fetchUsers() {
	if (users.value.length > 0) return; // Already fetched
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.utils.get_system_users",
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
			url: "/api/method/one_bpmn.api.canvas_comments.get_canvas_comments",
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
		const openTasks = elementComments.filter(c => c.is_task && c.status === "Open");
		
		if (openTasks.length === 0) return;

		// Create numeric badge HTML
		const html = document.createElement("div");
		html.className = "flex items-center justify-center bg-orange-500 text-white rounded-full text-[10px] font-extrabold shadow-sm border border-white cursor-pointer hover:scale-110 transition-transform";
		html.style.width = "18px";
		html.style.height = "18px";
		html.innerText = openTasks.length;
		html.title = `${openTasks.length} open task(s)`;

		html.onclick = (e) => {
			e.stopPropagation();
			// Select the element
			navigateToElementComments(elementId);
			// Open timeline and filter to open tasks
			showTimeline.value = true;
			timelineFilterMode.value = "element";
			timelineTaskFilter.value = true;
		};

		const elementRegistry = modeler.get("elementRegistry");
		const targetElement = elementRegistry.get(elementId);
		
		if (!targetElement) return;

		try {
			overlays.add(elementId, "processa-comment", {
				position: {
					bottom: -2,
					left: -2
				},
				html: html,
				scale: false
			});
		} catch (err) {
			console.error(`Failed to add overlay for element ${elementId}:`, err);
		}
	});
}

async function submitComment() {
	if (!commentFormData.value.text || !props.modelName) return;

	// Comments must be associated with a specific element — reject root/process
	const elementId = activeCommentElement.value?.id;
	if (!elementId || !activeCommentElement.value?.parent) {
		console.warn("Cannot add comment: no shape selected");
		return;
	}

	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.canvas_comments.post_canvas_comment",
			params: {
				model_name: props.modelName,
				element_id: elementId,
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
			url: "/api/method/one_bpmn.api.canvas_comments.update_comment_status",
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

	// Flush active properties panel text inputs to commit debounced values
	if (document.activeElement && typeof document.activeElement.blur === "function") {
		document.activeElement.blur();
	}

	// Commit any active direct editing on the canvas
	try {
		const directEditing = modeler.get("directEditing");
		if (directEditing && directEditing.isActive()) {
			directEditing.complete();
		}
	} catch (e) {
		console.warn("Could not complete active direct editing:", e);
	}

	const { xml } = await modeler.saveXML({ format: true });
	return xml;
}


async function loadXML(xml) {
	if (!modeler) return;
	isImporting.value = true;
	try {
		await modeler.importXML(xml);

		// Proactively auto-layout connecting lines (edges) using bpmn-js's native layout engine.
		// This translates straight-line connectors or missing edge DI elements into standard
		// orthogonal Manhattan routing paths that avoid node overlapping.
		try {
			const elementRegistry = modeler.get("elementRegistry");
			const modeling = modeler.get("modeling");
			const connections = elementRegistry.filter(
				(el) => el.type === "bpmn:SequenceFlow" || (el.waypoints && el.source && el.target)
			);
			for (const conn of connections) {
				try {
					// Only re-layout connections that look like diagonal straight lines
					// (2 waypoints where the Y coordinates differ significantly).
					// Do NOT mutate conn.waypoints directly — that corrupts bpmn-js
					// internal state and causes "Cannot read properties of undefined
					// (reading 'segmentIndex')" errors.
					if (
						conn.waypoints &&
						conn.waypoints.length === 2 &&
						Math.abs(conn.waypoints[0].y - conn.waypoints[1].y) > 5
					) {
						modeling.layoutConnection(conn);
					}
				} catch (singleLayoutErr) {
					// Swallow per-connection errors so one bad edge doesn't break the rest
					console.warn("Auto-layout skipped for connection", conn.id, singleLayoutErr);
				}
			}
		} catch (layoutErr) {
			console.warn("Auto-layout connections failed:", layoutErr);
		}

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

async function getCanvasXml() {
	if (!modeler) return "";
	try {
		const { xml } = await modeler.saveXML({ format: false });
		return xml || "";
	} catch {
		return "";
	}
}

async function onProsAllyBpmnGenerated(xml) {
	if (!xml) return;
	await loadXML(layoutBpmnXml(xml));
	emit("changed");
}

/**
 * Set the `name` attribute on the first <bpmn:process> element.
 * Uses the modeler's modeling API so the change is reflected
 * immediately in the properties panel and serialised into XML on save.
 */
function setProcessName(name) {
	if (name) internalProcessName.value = name;
	if (!modeler || !name) return;
	try {
		const elementRegistry = modeler.get("elementRegistry");
		const modeling = modeler.get("modeling");
		// Find the root process element(s)
		const processElements = elementRegistry.filter(
			(el) => el.type === "bpmn:Process"
		);
		for (const processEl of processElements) {
			if (!processEl.businessObject.name) {
				modeling.updateProperties(processEl, { name });
			}
		}
	} catch (e) {
		console.warn("Could not set process name:", e);
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

function getInitials(fullName) {
	if (!fullName) return "??";
	return fullName
		.split(" ")
		.map((n) => n[0])
		.join("")
		.toUpperCase()
		.substring(0, 2);
}

function getAvatarColor(userName) {
	const colors = [
		"bg-red-500", "bg-blue-500", "bg-green-500", "bg-yellow-500",
		"bg-purple-500", "bg-pink-500", "bg-indigo-500", "bg-teal-500",
		"bg-orange-500", "bg-cyan-500"
	];
	let hash = 0;
	for (let i = 0; i < (userName || "").length; i++) {
		hash = (userName || "").charCodeAt(i) + ((hash << 5) - hash);
	}
	return colors[Math.abs(hash) % colors.length];
}
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
	padding: 6px 6px;
	margin: 2px 8px;
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

/* Canvas Focus — suppress browser default outline on all focusable children.
   bpmn-js adds tabindex="0" on its root SVG, which triggers a visible
   outline (color/style/width/offset) on focus in Chromium.
   Reset all four sub-properties individually to override the UA stylesheet. */
.bpmn-canvas:focus,
.bpmn-canvas *:focus,
.bpmn-canvas svg[tabindex]:focus,
.bpmn-canvas svg[tabindex="0"]:focus {
	outline: none !important;
	outline-color: transparent !important;
	outline-style: none !important;
	outline-width: 0 !important;
	outline-offset: 0 !important;
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
	margin-bottom: 4px;
	margin-top: 8px;
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

/* Comment Textarea Improvements */
.timeline-textarea,
.inline-comment-textarea,
.main-comment-textarea textarea {
	line-height: 1.625 !important; /* leading-relaxed */
	transition: padding-bottom 0.2s ease, height 0.1s ease;
}

.timeline-textarea::placeholder,
.inline-comment-textarea::placeholder {
	color: #9ca3af;
}

.properties-panel-container .bio-properties-panel-input::placeholder {
	color: #9ca3af;
}

/* Checkbox Styling */
.properties-panel-container .bio-properties-panel-checkbox {
	display: flex;
	align-items: center;
	gap: 6px;
	cursor: pointer;
}

.properties-panel-container .bio-properties-panel-checkbox input[type="checkbox"] {
	width: 16px;
	height: 16px;
	min-width: 16px;
	border-radius: 4px;
	border: 1px solid #d1d5db;
	cursor: pointer;
	accent-color: #2490ef;
}

.properties-panel-container .bio-properties-panel-checkbox input[type="checkbox"]:checked {
	background-color: #2490ef;
	border-color: #2490ef;
}

/* Group Entries */
.properties-panel-container .bio-properties-panel-entry {
	padding: 4px 4px;
	margin: 0px 8px;
}

/* Description text in properties panel entries */
.properties-panel-container .bio-properties-panel-description {
	word-wrap: break-word;
	max-width: 350px;
	font-size: 11px;
	color: #6b7280;
	line-height: 1.4;
	margin-top: 2px;
	padding: 0 4px;
}

.properties-panel-container .bio-properties-panel-group-entries > .bio-properties-panel-description {
	padding-inline: 15px;
	padding-block: 5px;
}

/* Nested group entries (e.g. Correlation Properties) */
.properties-panel-container .bio-properties-panel-group-entries.open > .bio-properties-panel-group {
	margin-inline: 15px;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
	margin-bottom: 5px;
}

.properties-panel-container .bio-properties-panel-group-entries {
	border-bottom: 1px solid #f3f4f6;
	padding-bottom: 4px;
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
	transition: transform 0.3s ease, opacity 0.3s ease, width 0.3s ease;
}
.slide-right-enter-from, .slide-right-leave-to {
	transform: translateX(100%);
	opacity: 0;
}

/* Ensure the leaving panel doesn't occupy space in the flex flow during transition,
   preventing jerky layout shifts when switching between panels. */
.slide-right-enter-active,
.comment-panel-container.slide-right-leave-active,
.properties-panel-container.slide-right-leave-active {
	width: 0 !important;
	min-width: 0 !important;
	overflow: hidden !important;
	z-index: 50;
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

/* ── ProsAlly Panel slide transition ────────────────────────────────── */
.prosally-slide-enter-active,
.prosally-slide-leave-active {
	transition: width 0.3s ease, opacity 0.2s ease;
	overflow: hidden;
}
.prosally-slide-enter-from,
.prosally-slide-leave-to {
	width: 0 !important;
	opacity: 0;
}
.prosally-slide-enter-to,
.prosally-slide-leave-from {
	width: 20rem; /* w-80 */
	opacity: 1;
}

.prosally-panel-container {
	min-width: 0;
	overflow: hidden;
}
</style>
