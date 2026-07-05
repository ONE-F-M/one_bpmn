<template>
	<div class="h-full flex flex-col min-w-0 overflow-hidden">
		<!-- Unified Toolbar -->
		<header class="bg-white border-b px-2 py-2 flex items-center justify-between shadow-sm w-full min-h-[44px] sm:min-h-[48px]">
			
			<div class="flex items-center gap-2 flex-1 min-w-0">
				<!-- Left: Back & Title -->
				<div class="flex items-center gap-2 pr-3 sm:border-r sm:border-gray-200 min-w-0 shrink">
					<button
						v-if="!compact"
						@click="goBack"
						class="p-1.5 hover:bg-gray-100 rounded-md transition-colors text-gray-600 shrink-0"
						title="Back to list"
					>
						<Icon icon="lucide:chevron-left" class="w-5 h-5" />
					</button>
					<div class="flex items-center gap-2 relative min-w-0">
						<h1 class="text-sm font-semibold text-gray-800 truncate max-w-[120px] sm:max-w-[180px] lg:max-w-[260px]" :title="processName">{{ processName }}</h1>
						
						<!-- Status Icon -->
						<button 
							@click="showStatusPopup = !showStatusPopup"
							class="p-1 rounded transition-colors"
							:class="isEditable ? 'text-green-500 hover:bg-green-50' : 'text-amber-500 hover:bg-amber-50'"
						>
							<Icon :icon="isEditable ? 'lucide:pencil' : 'lucide:lock'" class="w-4 h-4" />
						</button>

						<!-- Status Popup -->
						<div 
							v-if="showStatusPopup"
							v-click-outside="() => showStatusPopup = false"
							class="absolute top-full left-0 mt-2 w-72 bg-white border border-gray-200 rounded-lg shadow-xl z-[60] overflow-hidden"
						>
							<div class="p-4 space-y-3">
								<div class="flex items-start gap-3">
									<div 
										class="p-2 rounded-lg shrink-0"
										:class="isEditable ? 'bg-green-50 text-green-600' : 'bg-amber-50 text-amber-600'"
									>
										<Icon :icon="isEditable ? 'lucide:pencil' : 'lucide:lock'" class="w-5 h-5" />
									</div>
									<div class="space-y-1">
										<h3 class="text-sm font-bold text-gray-900 leading-none">
											{{ isEditable ? 'Active Editing Session' : 'Document is Locked' }}
										</h3>
										<p class="text-xs text-gray-500 leading-relaxed">
											{{ isEditable ? 'This document is live and available for editing. Your changes are automatically saved and synchronized with the server.' : editabilityInfo.reason || 'No active Pathfinder Log. Create one on Production to enable editing.' }}
										</p>
									</div>
								</div>

								<div class="flex justify-end pt-2">
									<Button 
										variant="solid" 
										size="sm" 
										@click="showStatusPopup = false"
									>
										OK
									</Button>
								</div>
							</div>
						</div>

						<Badge v-if="processStatus" :theme="getStatusTheme(processStatus)" :label="processStatus" size="sm" />
					</div>

					<!-- Compact mode: Diagram dropdown selector (replaces bottom tab bar) -->
					<div v-if="compact && openTabs.length > 1" class="relative ml-1 sm:ml-2">
						<button
							@click="showCompactDiagramMenu = !showCompactDiagramMenu"
							class="flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 py-1.5 sm:py-1 rounded-md text-xs font-medium border transition-colors active:bg-gray-200"
							:class="showCompactDiagramMenu ? 'bg-gray-100 border-gray-300 text-gray-900' : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'"
						>
							<span
								:class="[
									'w-1.5 h-1.5 rounded-full shrink-0',
									activeDiagramIsActive ? 'bg-green-500' : 'bg-orange-400'
								]"
							></span>
							<span class="truncate max-w-[80px] sm:max-w-[120px]">{{ activeDiagramLabel }}</span>
							<Icon icon="lucide:chevron-down" class="w-3.5 h-3.5 shrink-0" />
						</button>
						<div
							v-if="showCompactDiagramMenu"
							v-click-outside="() => showCompactDiagramMenu = false"
							class="absolute top-full left-0 sm:left-0 mt-1 w-[calc(100vw-2rem)] sm:w-56 max-w-[280px] bg-white border border-gray-200 rounded-lg shadow-lg z-[70] py-1 max-h-64 overflow-y-auto"
						>
							<button
								v-for="tab in openTabs"
								:key="tab.name"
								@click="selectDiagram(tab.name); showCompactDiagramMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2.5 sm:py-2 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
								:class="{ 'bg-gray-50 font-semibold text-gray-900': activeDiagramName === tab.name }"
							>
								<span
									:class="[
										'w-2 h-2 rounded-full shrink-0',
										tab.is_active ? 'bg-green-500' : 'bg-orange-400'
									]"
								></span>
								<span class="truncate">{{ tab.model_name }}</span>
								<Icon v-if="activeDiagramName === tab.name" icon="lucide:check" class="w-3.5 h-3.5 text-blue-500 ml-auto shrink-0" />
							</button>
						</div>
					</div>
				</div>

				<!-- CENTER: BPMN Tools Container (Mounted natively from BpmnEditor.vue, hidden on mobile) -->
				<div id="bpmn-editor-toolbar" class="hidden sm:flex flex-1 items-center h-8 min-w-0"></div>

				<!-- Other Active Editors Avatars (hidden on mobile) -->
				<div v-if="otherEditors.length > 0" class="hidden sm:flex items-center -space-x-2 ml-4">
					<div
						v-for="user in otherEditors"
						:key="user.name"
						class="relative group"
					>
						<img
							v-if="user.user_image"
							:src="user.user_image"
							:alt="user.full_name"
							class="w-7 h-7 rounded-full border-2 border-white object-cover"
						/>
						<div
							v-else
							:class="[
								'w-7 h-7 rounded-full border-2 border-white flex items-center justify-center text-[10px] font-bold text-white uppercase',
								getAvatarColor(user.name)
							]"
						>
							{{ getInitials(user.full_name) }}
						</div>
						
						<!-- Hover Tooltip -->
						<div class="absolute top-full left-1/2 -translate-x-1/2 mt-2 hidden group-hover:block z-[60]">
							<div class="bg-gray-800 text-white text-[11px] py-1 px-2 rounded shadow-lg whitespace-nowrap">
								{{ user.full_name }} is editing
							</div>
							<div class="w-2 h-2 bg-gray-800 rotate-45 absolute -top-1 left-1/2 -translate-x-1/2"></div>
						</div>
					</div>
				</div>
			</div>
			
			<div class="flex items-center gap-2 shrink-0 border-l border-gray-200 pl-3 ml-2">
				
				<!-- Hidden file input for BPMN import -->
				<input
					ref="importFileInput"
					type="file"
					accept=".bpmn"
					class="hidden"
					@change="handleImportFile"
				/>

				<!-- Hidden file input for config JSON import -->
				<input
					ref="importConfigFileInput"
					type="file"
					accept=".json"
					class="hidden"
					@change="handleImportConfigFile"
				/>



				<!-- Desktop: Individual action buttons -->
				<template v-if="!isMobile">
					<!-- Version History Button -->
					<button
						@click="toggleVersionHistory"
						class="w-8 h-8 flex items-center justify-center rounded transition-colors"
						:class="[
							showVersionHistory ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100 text-gray-600',
							{ 'opacity-40 cursor-not-allowed': !activeDiagramName }
						]"
						:title="lastEditTooltip"
						:disabled="!activeDiagramName"
					>
						<Icon icon="lucide:history" class="w-4 h-4" />
					</button>

					<!-- Comments Sidebar Toggle -->
					<button
						@click="toggleComments"
						class="w-8 h-8 flex items-center justify-center rounded transition-colors relative"
						:class="[
							editorRef?.showTimeline ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-100 text-gray-600',
							{ 'opacity-40 cursor-not-allowed': !activeDiagramName }
						]"
						title="Toggle Comments Panel"
						:disabled="!activeDiagramName"
					>
						<Icon icon="lucide:message-square" class="w-4 h-4" />
						<span v-if="totalCommentCount > 0" class="absolute top-1 right-1 w-3 h-3 bg-blue-600 text-white text-[8px] font-bold rounded-full flex items-center justify-center border border-white">
							{{ totalCommentCount }}
						</span>
					</button>

					<!-- File menu dropdown (Import / Export) -->
					<div class="relative">
						<button
							@click="showFileMenu = !showFileMenu"
							class="w-8 h-8 flex items-center justify-center hover:bg-gray-100 rounded transition-colors text-gray-600"
							title="Import / Export"
						>
							<Icon icon="lucide:arrow-down-up" class="w-4 h-4" />
						</button>
						<div
							v-if="showFileMenu"
							v-click-outside="() => showFileMenu = false"
							class="absolute right-0 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg z-[70] py-1"
						>
							<button
								@click="triggerImport(); showFileMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							>
								<Icon icon="lucide:download" class="w-4 h-4" />
								Import BPMN
							</button>
							<button
								@click="triggerImportConfig(); showFileMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							>
								<Icon icon="lucide:file-json" class="w-4 h-4" />
								Import Config
							</button>
							<div class="border-t border-gray-100 my-1"></div>
							<button
								@click="exportCurrentDiagram(); showFileMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
								:disabled="!activeDiagramName"
								:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
							>
								<Icon icon="lucide:upload" class="w-4 h-4" />
								Export
							</button>
						</div>
					</div>

					<!-- Deploy / Disable Button (last — primary action, only for executable processes) -->
					<template v-if="isExecutable">
						<button
							v-if="isActiveModel"
							@click="disableModel"
							class="h-7 flex items-center gap-1 px-2.5 bg-red-600 hover:bg-red-700 text-white rounded transition-colors text-xs font-medium leading-none"
							title="Disable process map — stops new instances"
							:disabled="!activeDiagramName || disabling"
							:class="{ 'opacity-50 cursor-not-allowed': !activeDiagramName || disabling }"
						>
							<Icon :icon="disabling ? 'lucide:loader-2' : 'lucide:power-off'" class="w-3.5 h-3.5" :class="{ 'animate-spin': disabling }" />
							{{ disabling ? 'Disabling…' : 'Disable' }}
						</button>
						<button
							v-else
							@click="deployModel"
							class="h-7 flex items-center gap-1 px-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors text-xs font-medium leading-none"
							title="Deploy process model"
							:disabled="!activeDiagramName || deploying"
							:class="{ 'opacity-50 cursor-not-allowed': !activeDiagramName || deploying }"
						>
							<Icon :icon="deploying ? 'lucide:loader-2' : 'lucide:rocket'" class="w-3.5 h-3.5" :class="{ 'animate-spin': deploying }" />
							{{ deploying ? 'Deploying…' : 'Deploy' }}
						</button>
					</template>
				</template>

				<!-- Mobile: "More" overflow dropdown -->
				<div v-if="isMobile" class="relative">
					<button
						@click="showMobileMoreMenu = !showMobileMoreMenu"
						class="w-8 h-8 flex items-center justify-center hover:bg-gray-100 rounded transition-colors text-gray-600"
						title="More actions"
					>
						<Icon icon="lucide:more-vertical" class="w-4 h-4" />
					</button>
					<div
						v-if="showMobileMoreMenu"
						v-click-outside="() => showMobileMoreMenu = false"
						class="absolute right-0 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1"
					>
						<template v-if="isExecutable">
							<button
								v-if="isActiveModel"
								@click="disableModel(); showMobileMoreMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
								:disabled="!activeDiagramName || disabling"
								:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName || disabling }"
							>
								<Icon :icon="disabling ? 'lucide:loader-2' : 'lucide:power-off'" class="w-4 h-4" />
								{{ disabling ? 'Disabling…' : 'Disable' }}
							</button>
							<button
								v-else
								@click="deployModel(); showMobileMoreMenu = false"
								class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
								:disabled="!activeDiagramName || deploying"
								:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName || deploying }"
							>
								<Icon :icon="deploying ? 'lucide:loader-2' : 'lucide:rocket'" class="w-4 h-4" />
								{{ deploying ? 'Deploying…' : 'Deploy' }}
							</button>
						</template>
						<button
							@click="toggleVersionHistory(); showMobileMoreMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							:disabled="!activeDiagramName"
							:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						>
							<Icon icon="lucide:history" class="w-4 h-4" />
							Version history
						</button>
						<div class="border-t border-gray-100 my-1"></div>
						<button
							@click="triggerImport(); showMobileMoreMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						>
							<Icon icon="lucide:download" class="w-4 h-4" />
							Import BPMN
						</button>
						<button
							@click="triggerImportConfig(); showMobileMoreMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						>
							<Icon icon="lucide:file-json" class="w-4 h-4" />
							Import Config
						</button>
						<button
							@click="exportCurrentDiagram(); showMobileMoreMenu = false"
							class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							:disabled="!activeDiagramName"
							:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						>
							<Icon icon="lucide:upload" class="w-4 h-4" />
							Export
						</button>
					</div>
				</div>


			</div>
		</header>


		<!-- Notification Banner (Background) -->
		<div v-if="notification.show && !isAnyDialogOpen" class="px-4 py-2">
			<div
				class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm shadow-sm border"
				:class="{
					'bg-green-50 border-green-200 text-green-800': notification.theme === 'green',
					'bg-red-50 border-red-200 text-red-800': notification.theme === 'red',
					'bg-yellow-50 border-yellow-200 text-yellow-800': notification.theme === 'yellow',
					'bg-blue-50 border-blue-200 text-blue-800': !notification.theme || notification.theme === 'blue',
				}"
			>
				<!-- Icon -->
				<Icon
					:icon="notification.theme === 'green' ? 'lucide:check-circle-2' : notification.theme === 'red' ? 'lucide:alert-circle' : 'lucide:info'"
					class="w-5 h-5 mt-0.5 flex-shrink-0"
				/>
				<!-- Content -->
				<div class="flex-1 min-w-0">
					<p class="font-semibold">{{ notification.title }}</p>
					<p v-if="notification.message" class="mt-0.5 whitespace-pre-line break-words">{{ notification.message }}</p>
				</div>
				<!-- Close button -->
				<button
					@click="notification.show = false"
					class="flex-shrink-0 p-0.5 rounded hover:bg-black/10 transition-colors"
					aria-label="Dismiss notification"
				>
					<Icon icon="lucide:x" class="w-4 h-4" />
				</button>
			</div>
		</div>

		<!-- Main Content -->
		<div :class="['flex-1 flex flex-col', isMobile ? '' : 'overflow-hidden']">
			<!-- Canvas Area -->
			<div :class="['flex-1 flex', isMobile ? '' : 'overflow-hidden']">

				<!-- Canvas -->

				<div class="flex-1 relative">
					<!-- Loading state -->
					<div v-if="loading" class="flex items-center justify-center h-full bg-gray-100">
						<div class="text-center">
							<div
								class="animate-spin rounded-full h-12 w-12 border-b-2 border-gray-700 mx-auto mb-4"
							></div>
							<p class="text-gray-500">Loading...</p>
						</div>
					</div>

					<!-- Single long-lived modeler instance; mounts on first diagram selection.
					     Clipboard state (globalClipboardData) lives at module scope so it
					     survives unmount — v-if is safe here and defers the heavy init. -->
					<BpmnEditor
						v-if="activeDiagramName"
						ref="editorRef"
						class="absolute inset-0"
						:save-status-text="saveStatusText"
						:save-status-color="saveStatusColor"
						:readonly="!isEditable"
						:model-name="activeDiagramName"
						@ready="onEditorReady"
						@changed="onDiagramChanged"
						@zoom-changed="onZoomChanged"
						@launch-script-editor="onLaunchScriptEditor"
						@confirm-script-delete="onConfirmScriptDelete"
						@launch-markdown-editor="onLaunchMarkdownEditor"
						@launch-callactivity-editor="onLaunchCallActivityEditor"
						@launch-callactivity-search="onLaunchCallActivitySearch"
						@launch-notification-editor="onLaunchNotificationEditor"
						@launch-dmn-editor="onLaunchDmnEditor"
						@launch-notify-assignee-editor="onLaunchNotifyAssigneeEditor"
					/>

					<!-- No-diagram placeholder: only shown when not loading and no diagram is selected -->
					<div
						v-if="!loading && !activeDiagramName"
						class="flex items-center justify-center h-full bg-gray-100"
					>
						<div class="text-center">
							<div class="text-gray-400 mb-6">
								<Icon icon="lucide:layout-grid" class="w-20 h-20 mx-auto" />
							</div>
							<p class="text-gray-500 text-lg mb-6">No process map selected</p>
							<button
								v-if="isEditable"
								@click="showAddDiagramDialog"
								class="inline-flex items-center gap-2 px-5 py-3 bg-gray-700 hover:bg-gray-800 text-white rounded-lg transition-colors font-medium"
							>
								<Icon icon="lucide:plus" class="w-5 h-5" />
								Add Process Map
							</button>
							<p v-else class="text-sm text-gray-400">
								<Icon icon="lucide:lock" class="w-4 h-4 inline mr-1" />
								Process is locked. Create a Pathfinder Log to enable editing.
							</p>
						</div>
					</div>
				</div>

				<!-- Version History side panel (Google-Docs-style) -->
				<VersionHistoryPanel
					v-if="showVersionHistory && activeDiagramName"
					ref="versionHistoryRef"
					:modelName="activeDiagramName"
					:getCurrentXml="getCurrentDiagramXml"
					@close="showVersionHistory = false"
					@error="(e) => showNotification(e.title, e.message, e.theme)"
					@restored="onVersionRestored"
					@compare-deployed="openVersionPicker"
				/>
			</div>

			<!-- Tab Bar (hidden in compact mode — uses toolbar dropdown instead) -->
			<div v-if="openTabs.length > 0 && !compact" class="relative z-10 flex items-center justify-between bg-white border-t border-gray-200 min-h-[40px]">
				<EditorTabs
					:tabs="openTabs"
					:activeTab="activeDiagramName"
					:readonly="!isEditable"
					@select-tab="selectDiagram"
					@add-tab="showAddDiagramDialog"
					@rename-tab="renameProcessModel"
					@duplicate-tab="handleDuplicateTab"
					@delete-tab="handleDeleteTab"
					class="flex-1 min-w-0"
				/>
				
				<!-- Zoom Controls -->
				<div class="hidden sm:flex items-center gap-1 px-3 py-2 border-l border-gray-300">
					<button
						@click="handleZoomOut"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
						title="Zoom Out (Ctrl+-)"
					>
						<Icon icon="lucide:minus" class="w-4 h-4" />
					</button>
					<button
						@click="handleResetZoom"
						class="px-2 py-1 rounded hover:bg-gray-300 text-gray-700 text-sm font-medium min-w-[50px] text-center transition-colors"
						title="Reset Zoom"
					>
						{{ zoomLevel }}%
					</button>
					<button
						@click="handleZoomIn"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors"
						title="Zoom In (Ctrl++)"
					>
						<Icon icon="lucide:plus" class="w-4 h-4" />
					</button>
					<button
						@click="handleFitToScreen"
						class="p-1.5 rounded hover:bg-gray-300 text-gray-600 transition-colors ml-1"
						title="Fit to Screen"
					>
						<Icon icon="lucide:maximize-2" class="w-4 h-4" />
					</button>
				</div>
			</div>
		</div>

		<!-- Add Process Map / New Version Dialog -->
		<Dialog
			v-model="showNewDiagramDialog"
			:options="{ title: newDiagramMode === 'version' ? 'Create New Version' : 'New Process Map' }"
		>
			<template #body-content>
				<div class="space-y-4">
					<!-- Base version picker — only when the process already has a map -->
					<div v-if="newDiagramMode === 'version'">
						<label class="block text-sm font-medium text-gray-700 mb-1">
							Base version <span class="text-red-500">*</span>
						</label>
						<p class="text-xs text-gray-500 mb-2">
							Pick a named version from the history to use as the starting template for the new version.
						</p>
						<div v-if="loadingNamedVersions" class="text-sm text-gray-400 py-2">
							Loading named versions…
						</div>
						<div
							v-else-if="namedVersions.length === 0"
							class="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2"
						>
							No named versions found in the current map's history. Name a version in the history
							panel first, then create a new version from it.
						</div>
						<select
							v-else
							v-model="selectedBaseVersion"
							class="w-full text-sm border border-gray-300 rounded-md px-3 py-2 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
						>
							<option v-for="v in namedVersions" :key="v.name" :value="v.name">
								{{ v.version_name }} — {{ formatVersionTime(v.timestamp) }}
							</option>
						</select>
					</div>

					<FormControl
						:label="newDiagramMode === 'version' ? 'New Version Name' : 'Process Map Name'"
						v-model="newDiagramName"
						:required="true"
						placeholder="Enter a unique name"
					/>
					<FormControl
						label="Description"
						type="textarea"
						v-model="newDiagramDescription"
						placeholder="Optional description"
					/>

				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showNewDiagramDialog = false">Cancel</Button>
					<Button
						variant="solid"
						@click="createDiagram"
						:loading="creating"
						:disabled="newDiagramMode === 'version' && (loadingNamedVersions || namedVersions.length === 0)"
					>Create</Button>
				</div>
			</template>
		</Dialog>

		<!-- Server Script Selector/Creator Dialog -->
		<Dialog v-model="showScriptEditorDialog" :options="{ title: scriptEditorTitle, size: '5xl' }">
			<template #body-content>
				<div class="space-y-4">
					<!-- Mode Tabs -->
					<div class="flex border-b border-gray-200">
						<button
							@click="scriptDialogMode = 'select'"
							:class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px', scriptDialogMode === 'select' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
						>
							<Icon icon="lucide:search" class="w-4 h-4 inline mr-1.5" />Select Existing
						</button>
						<button
							@click="scriptDialogMode = 'create'"
							:class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px', scriptDialogMode === 'create' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
						>
							<Icon icon="lucide:plus" class="w-4 h-4 inline mr-1.5" />Create New
						</button>
						<button
							v-if="linkedScriptName"
							@click="scriptDialogMode = 'edit'"
							:class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px', scriptDialogMode === 'edit' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
						>
							<Icon icon="lucide:pencil" class="w-4 h-4 inline mr-1.5" />Edit
						</button>
						<button
							@click="openLogixCanvas"
							:class="['px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300']"
						>
							<Icon icon="lucide:bot" class="w-4 h-4 inline mr-1.5" />Logix Chat
						</button>
					</div>

					<!-- Select Existing Mode -->
					<div v-if="scriptDialogMode === 'select'" class="space-y-3">
						<div class="text-sm text-gray-500">Search and select an existing Server Script to link.</div>
						<div class="relative">
							<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
							<input v-model="serverScriptSearch" type="text" placeholder="Search server scripts..." class="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400" />
						</div>
						<div class="max-h-72 overflow-y-auto border border-gray-200 rounded-lg">
							<div v-if="loadingScripts" class="p-6 text-center text-gray-400">
								<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>Loading scripts...
							</div>
							<div v-else-if="filteredServerScripts.length === 0" class="p-6 text-center text-gray-400">No server scripts found.</div>
							<div v-else>
								<template v-for="script in filteredServerScripts" :key="script.name">
									<div
										@click="selectedServerScript = script.name"
										:class="['flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors', selectedServerScript === script.name ? 'bg-blue-50 border-l-4 border-l-blue-500' : 'hover:bg-gray-50']"
									>
										<div>
											<div class="text-sm font-medium text-gray-900">{{ script.name }}</div>
											<div class="text-xs text-gray-500 mt-0.5">{{ script.script_type }}<span v-if="script.reference_doctype"> · {{ script.reference_doctype }}</span></div>
										</div>
										<div class="flex items-center">
											<Icon v-if="selectedServerScript === script.name" icon="lucide:check-circle" class="w-5 h-5 text-blue-500" />
										</div>
									</div>
									<div v-if="selectedServerScript === script.name && previewScriptContent !== null" class="border-b border-gray-100 bg-gray-50/50">
										<div v-if="loadingPreview" class="px-4 py-3 text-center text-gray-400 text-sm">
											<div class="animate-spin rounded-full h-5 w-5 border-b-2 border-gray-400 mx-auto mb-1"></div>Loading...
										</div>
										<pre v-else class="px-4 py-3 text-[13px] font-mono text-gray-700 overflow-x-auto max-h-48 whitespace-pre-wrap">{{ previewScriptContent }}</pre>
									</div>
								</template>
							</div>
						</div>
					</div>

					<!-- Create New Mode -->
					<div v-else-if="scriptDialogMode === 'create'" class="space-y-4">
						<div class="text-sm text-gray-500">Create a new Server Script and link it to this element.</div>
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Script Name <span class="text-red-500">*</span></label>
								<input v-model="newScript.name" type="text" placeholder="e.g. Validate Employee Shift" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
							</div>
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Script Type <span class="text-red-500">*</span></label>
								<select v-model="newScript.script_type" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" :disabled="isScriptTaskElement">
									<template v-if="isScriptTaskElement"><option value="API">API</option></template>
									<template v-else>
										<option value="">Select type...</option>
										<option value="DocType Event">DocType Event</option>
										<option value="Scheduler Event">Scheduler Event</option>
										<option value="Permission Query">Permission Query</option>
										<option value="API">API</option>
									</template>
								</select>
							</div>
						</div>
						<div v-if="['DocType Event', 'Permission Query'].includes(newScript.script_type)" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Reference DocType</label>
								<div class="relative">
									<input v-model="doctypeSearch" type="text" :placeholder="newScript.reference_doctype || 'Search DocType...'" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" @focus="showDoctypeDropdown = true; showModuleDropdown = false; doctypeSearch = ''" @blur="setTimeout(() => showDoctypeDropdown = false, 200)" />
									<div v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
										<div v-for="dt in filteredDoctypeOptions" :key="dt" @mousedown.prevent="newScript.reference_doctype = dt; doctypeSearch = dt; showDoctypeDropdown = false" class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900">{{ dt }}</div>
									</div>
								</div>
							</div>
							<div v-if="newScript.script_type === 'DocType Event'">
								<label class="block text-xs font-medium text-gray-700 mb-1">DocType Event</label>
								<select v-model="newScript.doctype_event" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400">
									<option value="">Select event...</option>
									<option v-for="evt in doctypeEvents" :key="evt" :value="evt">{{ evt }}</option>
								</select>
							</div>
						</div>
						<div v-if="newScript.script_type === 'API'" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">API Method</label>
								<input v-model="newScript.api_method" type="text" placeholder="e.g. my_custom_api" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" />
							</div>
							<div class="flex items-end">
								<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
									<input type="checkbox" v-model="newScript.allow_guest" class="rounded border-gray-300" />Allow Guest
								</label>
							</div>
						</div>
						<div v-if="newScript.script_type === 'Scheduler Event'" class="grid grid-cols-2 gap-4">
							<div>
								<label class="block text-xs font-medium text-gray-700 mb-1">Event Frequency</label>
								<select v-model="newScript.event_frequency" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400">
									<option value="">Select frequency...</option>
									<option v-for="freq in eventFrequencies" :key="freq" :value="freq">{{ freq }}</option>
								</select>
							</div>
							<FormControl v-if="newScript.event_frequency === 'Cron'" label="Cron Format" v-model="newScript.cron_format" placeholder="*/5 * * * *" />
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Module (for export)</label>
							<div class="relative">
								<input v-model="moduleSearch" type="text" :placeholder="newScript.module || 'Search Module...'" class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400" @focus="showModuleDropdown = true; showDoctypeDropdown = false; moduleSearch = ''" @blur="setTimeout(() => showModuleDropdown = false, 200)" />
								<div v-if="showModuleDropdown && filteredModuleOptions.length > 0" class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg">
									<div v-for="mod in filteredModuleOptions" :key="mod" @mousedown.prevent="newScript.module = mod; moduleSearch = mod; showModuleDropdown = false" class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900">{{ mod }}</div>
								</div>
							</div>
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1">Script <span class="text-red-500">*</span></label>
							<textarea v-model="newScript.script" class="w-full h-48 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y" placeholder="# Enter Python script here..." spellcheck="false"></textarea>
						</div>
					</div>

					<!-- Edit Mode -->
					<div v-else-if="scriptDialogMode === 'edit'" class="space-y-4">
						<div class="flex items-center gap-3">
							<div class="flex-1">
								<div class="text-sm font-semibold text-gray-900">{{ linkedScriptName }}</div>
								<div v-if="editScriptMeta.script_type" class="text-xs text-gray-500 mt-0.5">{{ editScriptMeta.script_type }}<span v-if="editScriptMeta.reference_doctype"> · {{ editScriptMeta.reference_doctype }}</span></div>
							</div>
						</div>
						<div v-if="loadingEditScript" class="flex items-center justify-center py-12 text-gray-400">
							<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mr-2"></div>Loading script...
						</div>
						<div v-else>
							<label class="block text-xs font-medium text-gray-700 mb-1">Script</label>
							<textarea v-model="editScriptContent" class="w-full h-72 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y" spellcheck="false"></textarea>
						</div>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showScriptEditorDialog = false">Cancel</Button>
					<Button v-if="scriptDialogMode === 'select'" variant="solid" @click="saveScript" :disabled="!selectedServerScript">Link Script</Button>
					<Button v-else-if="scriptDialogMode === 'create'" variant="solid" @click="createAndLinkScript" :loading="creatingScript" :disabled="!newScript.name || !newScript.script_type || !newScript.script">Create &amp; Link</Button>
					<Button v-else-if="scriptDialogMode === 'edit'" variant="solid" @click="saveEditedScript" :loading="savingEditScript" :disabled="!editScriptContent || loadingEditScript">Save Changes</Button>
				</div>
			</template>
		</Dialog>

		<!-- Delete Script Confirmation Dialog -->
		<Dialog v-model="showDeleteScriptConfirm" :options="{ title: 'Delete Element', size: 'lg' }">
			<template #body-content>
				<div class="space-y-3 text-sm text-gray-700">
					<p>This element has a linked Server Script:</p>
					<ul class="list-disc pl-5 space-y-1">
						<li v-for="name in deleteScriptConfirmData.scriptNames" :key="name" class="font-medium text-gray-900">
							{{ name }}
							<span v-if="deleteScriptConfirmData.usageMap[name] > 1" class="ml-2 text-xs font-normal text-amber-600">
								(also used by {{ deleteScriptConfirmData.usageMap[name] - 1 }} other element{{ deleteScriptConfirmData.usageMap[name] > 2 ? 's' : '' }})
							</span>
						</li>
					</ul>
					<p class="text-gray-500 text-xs pt-1">Should the Server Script(s) be deleted as well?</p>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showDeleteScriptConfirm = false">Cancel</Button>
					<Button variant="ghost" @click="confirmDeleteElement(false)">Delete Element Only</Button>
					<Button variant="solid" theme="red" @click="confirmDeleteElement(true)">Delete Element &amp; Script</Button>
				</div>
			</template>
		</Dialog>

		<!-- Logix Canvas (AI Script Editor) -->
		<Dialog v-model="showLogixCanvas" :options="{ title: 'Logix AI Assistant', size: '7xl' }">
			<template #body-content>
				<LogixCanvas
					:element="logixElement"
					:script-type="logixScriptType"
					:current-script="logixCurrentScript"
					:event-bus="logixEventBus"
					:process-context="logixProcessContext"
					@close="showLogixCanvas = false"
					@script-saved="onLogixScriptSaved"
					@back="onLogixBack"
				/>
			</template>
		</Dialog>

		<!-- DMN Editor Dialog (Business Rule Task) — autosaves on every change -->
		<Dialog v-model="showDmnEditorDialog" :options="{ title: dmnEditorTitle, size: '7xl' }">
			<template #body-content>
				<div class="dmn-dialog-body">
					<DmnEditor
						v-if="showDmnEditorDialog"
						:key="dmnEditorKey"
						ref="dmnEditorRef"
						:initial-xml="dmnEditorXml"
						:readonly="!isEditable"
						@xml-changed="onDmnXmlChanged"
					/>
				</div>
			</template>
		</Dialog>

		<!-- Call Activity Search Dialog -->
		<CallActivitySearchDialog
			v-model="showCallActivitySearchDialog"
			:search-event="callActivitySearchEvent"
			@select="onCallActivitySelected"
			@cancel="onCancelCallActivitySearch"
		/>

		<!-- Markdown Editor Dialog -->
		<Dialog v-model="showMarkdownEditorDialog" :options="{ title: 'Edit Instructions (Markdown)', size: '4xl' }">
			<template #body-content>

				<div class="space-y-3">
					<div class="text-sm text-gray-500">
						Edit the markdown content for this element's instructions.
					</div>
					<TextEditor
						editor-class="prose-sm min-h-[16rem] border rounded-b-lg border-t-0 p-3"
						:content="markdownEditorContent"
						placeholder="Type instructions here..."
						@change="(val) => (markdownEditorContent = val)"
						:bubbleMenu="true"
						:fixedMenu="true"
					/>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button variant="subtle" @click="showMarkdownEditorDialog = false">Cancel</Button>
					<Button variant="solid" @click="saveMarkdown">Save</Button>
				</div>
			</template>
		</Dialog>

		<!-- Notification Selector/Creator Dialog (Send Task) -->
		<NotificationLinkDialog />

		<!-- Notify Assignee Editor Dialog (User Task) -->
		<NotifyAssigneeEditorDialog
			v-model="showNotifyAssigneeDialog"
			:initial-body="notifyAssigneeBody"
			:initial-subject="notifyAssigneeSubject"
			:initial-template="notifyAssigneeTemplate"
			@save="onSaveNotifyAssigneeBody"
		/>
		<Dialog v-model="showUnsavedNavigationWarning" :options="{ title: 'Unsaved Changes', size: 'sm' }">
			<template #body-content>
				<div class="text-base text-gray-700">
					You have unsaved changes. Are you sure you want to leave? Your pending edits will be lost.
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2 justify-end w-full">
					<Button variant="subtle" @click="cancelNavigation">No, stay here</Button>
					<Button variant="solid" theme="red" @click="confirmNavigation">Yes, leave</Button>
				</div>
			</template>
		</Dialog>

		<!-- Readiness Checklist Dialog (import & deploy) -->
		<ReadinessChecklistDialog
			v-model="showReadinessDialog"
			:checklist="readinessChecklist"
			:mode="readinessMode"
			:loading="readinessLoading"
			@close="onReadinessClose"
			@cancel="onReadinessCancel"
			@deploy="onReadinessDeploy"
			@upload-config="onReadinessUploadConfig"
			@recheck="onReadinessRecheck"
			@update-refs="onReadinessUpdateRefs"
		/>

		<!-- Export Config Dialog -->
		<ExportConfigDialog
			v-model="showExportConfigDialog"
			:counts="exportConfigCounts"
			@export-bpmn-only="doExportBpmnOnly"
			@export-with-config="doExportWithConfig"
		/>

		<!-- Config Import Results Dialog -->
		<ConfigImportResultsDialog
			v-model="showConfigImportResults"
			:results="configImportResults"
			:importing="configImporting"
			@done="onConfigImportDone"
		/>

		<!-- Disable Process Confirmation Dialog -->
		<Dialog v-model="showDisableDialog" :options="{ title: 'Disable Process Map', size: 'sm' }">
			<template #body-content>
				<div class="space-y-3">
					<div class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm border border-orange-200 bg-orange-50 text-orange-800">
						<Icon icon="lucide:alert-triangle" class="w-5 h-5 shrink-0 mt-0.5" />
						<div>
							<div class="font-semibold">This will stop all new instances from being created.</div>
							<div class="mt-1 opacity-90">Linked server scripts will be disabled. You can re-deploy at any time to reactivate.</div>
						</div>
					</div>
					<div v-if="disableRunningCount > 0" class="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm border border-blue-200 bg-blue-50 text-blue-800">
						<Icon icon="lucide:info" class="w-4 h-4 shrink-0" />
						<span><strong>{{ disableRunningCount }}</strong> running instance(s) will continue to completion.</span>
					</div>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2 justify-end w-full">
					<Button variant="subtle" @click="showDisableDialog = false">Cancel</Button>
					<Button variant="solid" theme="red" :loading="disabling" @click="executeDisable">Disable</Button>
				</div>
			</template>
		</Dialog>

		<!-- Version Comparison Dialogs (extracted component) -->
		<VersionDiffDialog
			ref="versionDiffRef"
			:diagramName="activeDiagramName"
			@error="(e) => showNotification(e.title, e.message, e.theme)"
		/>
	</div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch, nextTick, provide, inject } from "vue";
import { useRouter, useRoute, onBeforeRouteLeave } from "vue-router";
import { frappeRequest, TextEditor } from "frappe-ui";
import { Icon } from "@iconify/vue";
import BpmnEditor from "@/components/BpmnEditor.vue";
import EditorTabs from "@/components/EditorTabs.vue";

import VersionDiffDialog from "@/components/VersionDiffDialog.vue";
import VersionHistoryPanel from "@/components/VersionHistoryPanel.vue";
import { downloadBpmn } from "@/utils/downloadBpmn";
import CallActivitySearchDialog from "@/components/CallActivitySearchDialog.vue";
import LogixCanvas from "@/components/LogixCanvas.vue";
import DmnEditor from "@/components/DmnEditor.vue";
import NotificationLinkDialog from "@/components/NotificationLinkDialog.vue";
import NotifyAssigneeEditorDialog from "@/components/NotifyAssigneeEditorDialog.vue";
import ReadinessChecklistDialog from "@/components/ReadinessChecklistDialog.vue";
import ExportConfigDialog from "@/components/ExportConfigDialog.vue";
import ConfigImportResultsDialog from "@/components/ConfigImportResultsDialog.vue";
import { sanitiseFilename } from "@/utils/downloadBpmn";
import { useNotificationDialog } from "@/composables/useNotificationDialog";
import { useWindowSize } from "@/composables/useWindowSize";
import { dayjs } from "@/dayjs";

const { isMobile } = useWindowSize();

const props = defineProps({
	process: {
		type: String,
		required: true,
	},
	diagram: {
		type: String,
		default: null,
	},
	compact: {
		type: Boolean,
		default: false,
	},
});

// Compact mode: diagram dropdown state
const showCompactDiagramMenu = ref(false);

const activeDiagramLabel = computed(() => {
	const d = openTabs.value.find((t) => t.name === activeDiagramName.value);
	return d ? d.model_name : "Select Diagram";
});

const activeDiagramIsActive = computed(() => isActiveModel.value);

const router = useRouter();
const route = useRoute();

let heartbeatInterval = null;
const otherEditors = ref([]);

const editorRef = ref(null);
const processName = ref("");
const diagrams = ref([]);
const openTabs = ref([]);
const activeDiagramName = ref("");

const isAnyDialogOpen = computed(() => {
	return (
		showScriptEditorDialog.value ||
		showLogixCanvas.value ||
		showDeleteScriptConfirm.value ||
		showMarkdownEditorDialog.value ||
		showNewDiagramDialog.value ||
		showUnsavedNavigationWarning.value ||
		showCallActivitySearchDialog.value ||
		showReadinessDialog.value ||
		showDisableDialog.value ||
		showDmnEditorDialog.value ||
		showExportConfigDialog.value ||
		showConfigImportResults.value ||
		notifDialog.showNotificationDialog.value ||
		showNotifyAssigneeDialog.value ||
		versionDiffRef.value?.isAnyDialogOpen
	);
});

// --- Lifecycle ---
const saving = ref(false);
const creating = ref(false);
const importing = ref(false);
const editorReady = ref(false);
const hasUnsavedChanges = ref(false);
const loading = ref(true);

const showFileMenu = ref(false);
const showStatusPopup = ref(false);
const showMobileMoreMenu = ref(false);
const deploying = ref(false);
const disabling = ref(false);
const showDisableDialog = ref(false);
const disableRunningCount = ref(0);

// --- DMN Editor State ---
const showDmnEditorDialog = ref(false);
const dmnEditorRef = ref(null);
const dmnEditorTitle = ref("Edit Decision Model");
const dmnEditorXml = ref("");
const dmnEditorKey = ref(0); // Incremented on each open to force full recreation
let activeDmnElement = null;
let activeDmnEventBus = null;
let activeDmnDecisionId = null; // The decision_id to load/save — may differ from element.id

// Clean up DMN state when the dialog is closed (X button, click-outside, etc.)
watch(showDmnEditorDialog, (isOpen) => {
	if (!isOpen) {
		activeDmnElement = null;
		activeDmnEventBus = null;
		activeDmnDecisionId = null;
		// Reset XML so the next open doesn't flash stale content
		dmnEditorXml.value = "";
	}
});

// True when the currently selected diagram is deployed (is_active === 1)
const isActiveModel = computed(() => {
	if (!activeDiagramName.value) return false;
	const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
	return d ? !!d.is_active : false;
});

// True when the current diagram's BPMN process is marked as executable
const isExecutable = ref(false);

function extractIsExecutable(xml) {
	try {
		const doc = new DOMParser().parseFromString(xml, "text/xml");
		const processes = doc.getElementsByTagNameNS(
			"http://www.omg.org/spec/BPMN/20100524/MODEL",
			"process"
		);
		for (let i = 0; i < processes.length; i++) {
			if (processes[i].getAttribute("isExecutable") === "true") return true;
		}
		return false;
	} catch {
		return false;
	}
}

// Readiness checklist state
const showReadinessDialog = ref(false);
const readinessChecklist = ref(null);
const readinessMode = ref("import"); // "import" or "deploy"
const readinessLoading = ref(false);
let lastReadinessXml = ""; // XML used for the most recent readiness check (for recheck)

// Export config dialog state
const showExportConfigDialog = ref(false);
const exportConfigCounts = ref({ server_scripts: 0, workflow_states: 0, workflow_action_masters: 0 });
let pendingExportXml = ""; // XML to export after config dialog decision
let pendingExportTitle = ""; // Title for the BPMN download

// Config import results dialog state
const showConfigImportResults = ref(false);
const configImportResults = ref({ created: [], skipped: [], needs_confirmation: [] });
const configImporting = ref(false);

// Config import file input ref
const importConfigFileInput = ref(null);

// Version diff dialog ref
const versionDiffRef = ref(null);

// Version history side panel state
const showVersionHistory = ref(false);
const versionHistoryRef = ref(null);

// Pathfinder Log editability state
const isEditable = ref(false);  // locked by default until API confirms
const editabilityInfo = ref({
	editable: false,
	pathfinder_log: null,
	workflow_state: null,
	reason: null,
});

// Import file input ref
const importFileInput = ref(null);

// Auto-save state
const saveState = ref("idle"); // idle, unsaved, saving, saved, error
let saveTimeout = null;
let hasPendingSave = false; // true while the 1.5s debounce timer is counting down

// Returns true when there are edits that haven't reached the server yet
// (the debounce timer is ticking, a save is in-flight, or a save failed).
function isUnsavedOrInFlight() {
	return hasPendingSave || hasUnsavedChanges.value || saving.value;
}

// Derive status from the currently selected diagram tab
const processStatus = computed(() => {
	if (!activeDiagramName.value) return "";
	const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
	return d ? d.status : "";
});

const saveStatusText = computed(() => {
	switch (saveState.value) {
		case "unsaved": return "Unsaved changes";
		case "saving": return "Saving...";
		case "saved": return "Saved";
		case "error": return "Save Error";
		default: return "";
	}
});

const saveStatusColor = computed(() => {
	switch (saveState.value) {
		case "unsaved": return "text-orange-600";
		case "saving": return "text-blue-600";
		case "saved": return "text-green-600";
		case "error": return "text-red-600";
		default: return "text-transparent";
	}
});

const lastEditTooltip = computed(() => {
	if (!activeDiagramName.value) return "Version History";
	const d = diagrams.value.find((d) => d.name === activeDiagramName.value);
	if (!d || !d.modified) return "Version History";

	const modified = new Date(d.modified);
	const now = new Date();
	const diffMs = now - modified;
	const diffMins = Math.floor(diffMs / 60000);
	const diffHours = Math.floor(diffMs / 3600000);
	const diffDays = Math.floor(diffMs / 86400000);

	let timeStr;
	if (diffMins < 1) timeStr = "just now";
	else if (diffMins < 60) timeStr = `${diffMins} minute${diffMins > 1 ? "s" : ""} ago`;
	else if (diffHours < 24) timeStr = `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
	else if (diffDays === 1) timeStr = `yesterday at ${modified.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
	else timeStr = `on ${modified.toLocaleDateString()} at ${modified.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;

	const user = d.modified_by_name || "";
	return user ? `Last edit was made ${timeStr} by ${user}` : `Last edit was made ${timeStr}`;
});

// Notification state
const notification = ref({
	show: false,
	title: "",
	message: "",
	theme: "green"
});

// Navigation Warning Dialog state
const showUnsavedNavigationWarning = ref(false);
let pendingNavigationNext = null;

// New diagram dialog
const showNewDiagramDialog = ref(false);
const newDiagramName = ref("");
const newDiagramDescription = ref("");
// "blank" when the process has no map yet (create from scratch); "version" once
// a map exists (create a new version seeded from a chosen named version).
const newDiagramMode = ref("blank");
// Named versions from the active map's history, used as base-template choices.
const namedVersions = ref([]);
const loadingNamedVersions = ref(false);
const selectedBaseVersion = ref("");


// Track loaded diagram data
const diagramDataCache = ref({});

// Script Editor state
const showScriptEditorDialog = ref(false);
const scriptEditorTitle = ref("Link Server Script");
const scriptDialogMode = ref("select");
const serverScripts = ref([]);
const serverScriptSearch = ref("");
const selectedServerScript = ref(null);
const loadingScripts = ref(false);
const creatingScript = ref(false);
const showDoctypeDropdown = ref(false);
const showModuleDropdown = ref(false);
let activeScriptEvent = null;
const isScriptTaskElement = ref(false);

// Script preview state (Select Existing tab)
const previewScriptContent = ref(null);
const loadingPreview = ref(false);

// Edit tab state
const linkedScriptName = ref("");
const editScriptContent = ref("");
const editScriptMeta = ref({ script_type: "", reference_doctype: "" });
const loadingEditScript = ref(false);
const savingEditScript = ref(false);

// New Script form state
const newScript = ref({
	name: "",
	script_type: "",
	script: "",
	reference_doctype: "",
	doctype_event: "",
	api_method: "",
	allow_guest: false,
	event_frequency: "",
	cron_format: "",
	module: "",
});

// Options for select fields
const doctypeEvents = [
	"Before Insert", "Before Validate", "Before Save", "After Insert",
	"After Save", "Before Rename", "After Rename", "Before Submit",
	"After Submit", "Before Cancel", "After Cancel", "Before Delete",
	"After Delete", "Before Save (Submitted Document)",
	"After Save (Submitted Document)", "Before Print", "On Payment Authorization",
];
const eventFrequencies = [
	"All", "Hourly", "Daily", "Weekly", "Monthly", "Yearly",
	"Hourly Long", "Daily Long", "Weekly Long", "Monthly Long", "Cron",
];

// Computed: filtered scripts based on search (restricted to API for Script Tasks)
const filteredServerScripts = computed(() => {
	let list = serverScripts.value;
	if (isScriptTaskElement.value) {
		list = list.filter((s) => s.script_type === "API");
	}
	if (!serverScriptSearch.value) return list;
	const q = serverScriptSearch.value.toLowerCase();
	return list.filter(
		(s) =>
			s.name.toLowerCase().includes(q) ||
			(s.script_type && s.script_type.toLowerCase().includes(q)) ||
			(s.reference_doctype && s.reference_doctype.toLowerCase().includes(q))
	);
});

// Logix Canvas state
const showLogixCanvas = ref(false);
const logixElement = ref(null);
const logixScriptType = ref("bpmn:script");
const logixCurrentScript = ref("");
const logixEventBus = ref(null);
const logixProcessContext = ref(null);

function extractProcessContext(element) {
	if (!element?.businessObject) return null;
	const bo = element.businessObject;
	const mapNode = (ref) => ref ? {
		id:   ref.id,
		name: ref.name || ref.id,
		type: (ref.$type || "").replace("bpmn:", ""),
	} : null;
	const incoming = (bo.incoming || []).map(f => mapNode(f.sourceRef)).filter(Boolean);
	const outgoing  = (bo.outgoing  || []).map(f => mapNode(f.targetRef)).filter(Boolean);
	const process   = bo.$parent;
	return {
		element_id:   bo.id,
		element_name: bo.name || bo.id,
		process_name: process?.name || process?.id || "",
		incoming,
		outgoing,
	};
}

// Delete-with-script confirmation state
const showDeleteScriptConfirm = ref(false);
const deleteScriptConfirmData = ref({ elements: [], scriptNames: [], usageMap: {} });
let pendingDeleteElements = null;
let pendingDeleteModeling = null;

// Shared DocType/Module options (used by notification dialog composable)
const doctypeOptions = ref([]);
const moduleOptions = ref([]);
const doctypeSearch = ref("");
const moduleSearch = ref("");

// Computed: filtered DocType options based on search
const filteredDoctypeOptions = computed(() => {
	if (!doctypeSearch.value) return doctypeOptions.value.slice(0, 50);
	const q = doctypeSearch.value.toLowerCase();
	return doctypeOptions.value.filter((dt) => dt.toLowerCase().includes(q)).slice(0, 50);
});

// Computed: filtered Module options based on search
const filteredModuleOptions = computed(() => {
	if (!moduleSearch.value) return moduleOptions.value.slice(0, 50);
	const q = moduleSearch.value.toLowerCase();
	return moduleOptions.value.filter((m) => m.toLowerCase().includes(q)).slice(0, 50);
});

// Markdown Editor state
const showMarkdownEditorDialog = ref(false);
const markdownEditorContent = ref("");
let activeMarkdownEvent = null;

// Call Activity Search state
const showCallActivitySearchDialog = ref(false);
let callActivitySearchEvent = null; // plain variable — NOT a ref, because bpmn-js
// element objects have non-configurable/frozen properties (e.g. 'labels') that
// conflict with Vue 3's Proxy-based reactivity and cause TypeErrors.

// Notification Dialog (Send Task) — extracted into composable (Review Comment #1)
const notifDialog = useNotificationDialog(doctypeOptions, moduleOptions, showNotification);
provide("notifDialog", notifDialog);
provide("notification", notification);


// Zoom level (synced with BpmnEditor)
const zoomLevel = computed(() => currentZoomLevel.value);

// Zoom handlers
const currentZoomLevel = ref(100);

function handleZoomIn() {
	if (editorRef.value) {
		editorRef.value.zoomIn();
		updateZoomLevel();
	}
}

function handleZoomOut() {
	if (editorRef.value) {
		editorRef.value.zoomOut();
		updateZoomLevel();
	}
}

function handleResetZoom() {
	if (editorRef.value) {
		editorRef.value.resetZoom();
		updateZoomLevel();
	}
}

function handleFitToScreen() {
	if (editorRef.value) {
		editorRef.value.fitToScreen();
		// Wait for async zoom update
		setTimeout(() => updateZoomLevel(), 10);
	}
}

function updateZoomLevel() {
	if (editorRef.value && typeof editorRef.value.getZoomLevel === 'function') {
		currentZoomLevel.value = editorRef.value.getZoomLevel();
	}
}

function onZoomChanged(newZoom) {
	currentZoomLevel.value = newZoom;
}



// ── Readiness check (shared by import & deploy) ─────────────────────────
async function runReadinessCheck(xmlContent, mode) {
	readinessMode.value = mode;
	readinessChecklist.value = null;
	readinessLoading.value = true;
	showReadinessDialog.value = true;
	lastReadinessXml = xmlContent; // Store for recheck after config import

	try {
		const params = { xml_content: xmlContent };
		// When deploying, pass model_name so the backend can check for
		// call activity references to sibling models that will be disabled.
		if (mode === "deploy" && activeDiagramName.value) {
			params.model_name = activeDiagramName.value;
		}
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.validate_bpmn_readiness",
			params,
		});
		readinessChecklist.value = response.message || response;
	} catch (err) {
		console.error("Readiness check failed:", err);
		readinessChecklist.value = {
			categories: [
				{
					label: "Readiness Check Error",
					items: [
						{
							label: "Unable to validate BPMN readiness",
							status: "missing",
							message: "The readiness check failed. Please retry before importing or deploying.",
						},
					],
				},
			],
			total_checked: 1,
			total_missing: 1,
			total_warnings: 0,
			all_ready: false,
		};
	} finally {
		readinessLoading.value = false;
	}
}

function onReadinessClose() {
	showReadinessDialog.value = false;
}

function onReadinessCancel() {
	showReadinessDialog.value = false;
}

async function onReadinessDeploy() {
	showReadinessDialog.value = false;
	await executeDeployment();
}

// Upload config from readiness dialog (opens file picker)
function onReadinessUploadConfig() {
	if (importConfigFileInput.value) {
		importConfigFileInput.value.value = "";
		importConfigFileInput.value.click();
	}
}

// Recheck readiness after config import
async function onReadinessRecheck() {
	if (lastReadinessXml) {
		await runReadinessCheck(lastReadinessXml, readinessMode.value);
	}
}

// Update all call activity references and recheck
async function onReadinessUpdateRefs(refItems) {
	if (!refItems || refItems.length === 0) return;

	readinessLoading.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.update_call_activity_references",
			method: "POST",
			params: { references: JSON.stringify(refItems) },
		});

		const result = response.message || response;
		showNotification(
			"References Updated",
			`Updated ${result.updated || 0} call activity reference(s).`,
			"green"
		);

		// Recheck readiness to confirm the refs are resolved
		if (lastReadinessXml) {
			await runReadinessCheck(lastReadinessXml, readinessMode.value);
		}
	} catch (err) {
		const serverMessage =
			(err.messages && err.messages.length > 0)
				? err.messages.join("\n")
				: err.message || "An error occurred while updating references.";
		showNotification(
			"Update Failed",
			serverMessage,
			"red",
			true
		);
		readinessLoading.value = false;
	}
}

// Called when ConfigImportResultsDialog is done (all decisions applied)
async function onConfigImportDone() {
	// If readiness dialog is still open, recheck automatically
	if (showReadinessDialog.value && lastReadinessXml) {
		await runReadinessCheck(lastReadinessXml, readinessMode.value);
	}
}

// Deploy (compile) the process model
async function deployModel() {
	if (!activeDiagramName.value || deploying.value) return;

	// Get current XML for readiness check
	let xml = "";
	if (editorRef.value) {
		xml = await editorRef.value.getXML();
	}
	if (!xml) {
		showNotification("Deploy", "No diagram XML found.", "red");
		return;
	}

	// Run readiness check — dialog handles the rest
	await runReadinessCheck(xml, "deploy");
}

// Actual deployment (called after readiness check passes)
async function executeDeployment() {
	if (!activeDiagramName.value || deploying.value) return;

	deploying.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.compilation.compile_process_model",
			method: "POST",
			params: { model_name: activeDiagramName.value },
		});

		if (response && response.success) {
			showNotification(
				"Deployed",
				`Deployed successfully — version ${response.version}, ${response.subprocess_count} subprocess(es)`,
				"green"
			);

			// Show eval suite gating warnings (non-blocking)
			if (response.warnings && response.warnings.length > 0) {
				for (const warning of response.warnings) {
					showNotification("Eval Suite Warning", warning, "orange");
				}
			}

			// Update local state: mark this diagram as active, deactivate siblings
			for (const d of diagrams.value) {
				if (d.name === activeDiagramName.value) {
					d.is_active = 1;
					d.status = "Active";
					d.version = response.version;
				} else {
					d.is_active = 0;
					d.status = "Inactive";
				}
			}
		} else {
			showNotification("Deploy", "Deployment completed", "green");
		}
	} catch (err) {
		const serverMessage =
			(err.messages && err.messages.length > 0)
				? err.messages.join("\n")
				: err.message || "An error occurred while deploying the process model.";
		showNotification(
			"Deploy Failed",
			serverMessage,
			"red",
			true
		);
	} finally {
		deploying.value = false;
	}
}

// Disable a deployed process model (inverse of deploy)
async function disableModel() {
	if (!activeDiagramName.value || disabling.value) return;

	// Fetch running instance count for the confirmation dialog
	disableRunningCount.value = 0;
	try {
		const countResp = await frappeRequest({
			url: "/api/method/frappe.client.get_count",
			method: "GET",
			params: {
				doctype: "BPMN Process Instance",
				filters: JSON.stringify({
					process_model: activeDiagramName.value,
					status: ["in", ["Running", "Waiting"]],
				}),
			},
		});
		disableRunningCount.value = countResp || 0;
	} catch (e) {
		// Non-fatal — dialog will simply not show the count
	}

	showDisableDialog.value = true;
}

// Actual disable execution (called from confirmation dialog)
async function executeDisable() {
	if (!activeDiagramName.value || disabling.value) return;

	disabling.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.compilation.disable_process_model",
			method: "POST",
			params: { model_name: activeDiagramName.value },
		});

		showDisableDialog.value = false;

		if (response && response.success) {
			const runningMsg = response.running_instances
				? ` ${response.running_instances} running instance(s) will continue.`
				: "";
			showNotification(
				"Disabled",
				`Process map disabled successfully.${runningMsg}`,
				"orange"
			);

			// Update local state
			for (const d of diagrams.value) {
				if (d.name === activeDiagramName.value) {
					d.is_active = 0;
					d.status = "Inactive";
				}
			}
		}
	} catch (err) {
		showDisableDialog.value = false;
		const serverMessage =
			(err.messages && err.messages.length > 0)
				? err.messages.join("\n")
				: err.message || "An error occurred while disabling the process map.";
		showNotification(
			"Disable Failed",
			serverMessage,
			"red",
			true
		);
	} finally {
		disabling.value = false;
	}
}

// Keyboard shortcut handler
function handleKeyDown(event) {
	// Ctrl+S or Cmd+S to save (only when editable)
	if ((event.ctrlKey || event.metaKey) && event.key === "s") {
		event.preventDefault();
		if (isEditable.value && activeDiagramName.value && !saving.value) {
			saveCurrentDiagram();
		}
	}
	// Ctrl++ or Ctrl+= to zoom in
	if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
		event.preventDefault();
		handleZoomIn();
	}
	// Ctrl+- to zoom out
	if ((event.ctrlKey || event.metaKey) && event.key === "-") {
		event.preventDefault();
		handleZoomOut();
	}
	// Ctrl+0 to reset zoom
	if ((event.ctrlKey || event.metaKey) && event.key === "0") {
		event.preventDefault();
		handleResetZoom();
	}
}

function handleBeforeUnload(event) {
	// Guard fires when: edits are pending (debounce ticking), a save is in-flight, OR
	// a previous save failed and changes remain unsaved.
	if (isUnsavedOrInFlight()) {
		event.preventDefault();
		// returnValue must be set for Firefox; modern Chrome ignores the string.
		event.returnValue = "";
	}
}

// Prevent accidental navigation (clicking Back / going to a different Vue route)
onBeforeRouteLeave((to, from, next) => {
	if (isUnsavedOrInFlight()) {
		showUnsavedNavigationWarning.value = true;
		pendingNavigationNext = next;
	} else {
		next();
	}
});

function confirmNavigation() {
	showUnsavedNavigationWarning.value = false;
	if (pendingNavigationNext) {
		pendingNavigationNext(); // allow the route change to proceed
		pendingNavigationNext = null;
	}
}

function cancelNavigation() {
	showUnsavedNavigationWarning.value = false;
	if (pendingNavigationNext) {
		pendingNavigationNext(false); // block the route change
		pendingNavigationNext = null;
	}
}

onMounted(async () => {
	// Add keyboard shortcut listener
	window.addEventListener("keydown", handleKeyDown);
	window.addEventListener("beforeunload", handleBeforeUnload);

	try {
		loading.value = true;
		await loadProcess();

		// Check editability (Pathfinder Log status) from Production
		await checkEditability();

		// Add all diagrams to open tabs
		if (diagrams.value.length > 0) {
			openTabs.value = [...diagrams.value];
		}

		// If a specific diagram was passed in route, select it
		if (props.diagram) {
			activeDiagramName.value = props.diagram;
		} else if (diagrams.value.length > 0) {
			// Default to the active model; fallback to first (most recently modified)
			const activeDiagram = diagrams.value.find((d) => d.is_active || d.status === 'Active');
			activeDiagramName.value = activeDiagram
				? activeDiagram.name
				: diagrams.value[0].name;
		}
	} finally {
		loading.value = false;
	}
});

async function checkEditability() {

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.editability.check_process_editable",
			params: { process_name: props.process },
		});

		const data = response.message || response;
		isEditable.value = !!data.editable;
		editabilityInfo.value = {
			editable: !!data.editable,
			pathfinder_log: data.pathfinder_log || null,
			workflow_state: data.workflow_state || null,
			reason: data.reason || null,
		};
	} catch (error) {
		console.error("Failed to check process editability:", error);
		// On error, default to locked for safety
		isEditable.value = false;
		editabilityInfo.value = {
			editable: false,
			pathfinder_log: null,
			workflow_state: null,
			reason: "Unable to check editability. Process is locked for safety.",
		};
	}
}

onUnmounted(() => {
	// Remove listeners
	window.removeEventListener("keydown", handleKeyDown);
	window.removeEventListener("beforeunload", handleBeforeUnload);
	clearTimeout(saveTimeout);
	stopHeartbeat();
});

function startHeartbeat(modelName) {
	stopHeartbeat();
	if (!modelName) return;

	// Initial check
	performHeartbeat(modelName);

	// Periodic check every 30 seconds
	heartbeatInterval = setInterval(() => {
		performHeartbeat(modelName);
	}, 30000);
}

function stopHeartbeat() {
	if (heartbeatInterval) {
		clearInterval(heartbeatInterval);
		heartbeatInterval = null;
	}
	otherEditors.value = [];
}

async function performHeartbeat(modelName) {
	try {
		const response = await frappeRequest({
			url: "one_bpmn.api.editability.check_and_update_editor_lock",
			params: { model_name: modelName },
		});

		const otherUsers = response.message || response;
		
		if (otherUsers && otherUsers.length > 0) {
			otherEditors.value = otherUsers;
			// Multi-user editing is reflected by avatars in the header.
		} else {
			otherEditors.value = [];
		}
	} catch (err) {
		console.error("Heartbeat error:", err);
	}
}

async function loadProcess() {
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_diagrams",
			params: { process: props.process },
		});
		const data = response.message || response;
		processName.value = data.process_name;
		diagrams.value = data.diagrams || [];
	} catch (error) {
		console.error("Failed to load process:", error);
	}
}

async function selectDiagram(name) {
	if (activeDiagramName.value === name) return;

	// Save current diagram if there are unsaved changes
	if (hasUnsavedChanges.value && activeDiagramName.value && editorRef.value) {
		clearTimeout(saveTimeout);
		saving.value = true;
		await saveCurrentDiagram();
	}

	activeDiagramName.value = name;

	// Add to open tabs if not already there
	if (!openTabs.value.find((t) => t.name === name)) {
		const diagram = diagrams.value.find((d) => d.name === name);
		if (diagram) {
			openTabs.value.push(diagram);
		}
	}

	// Update URL (skip in compact mode — parent manages routing)
	if (!props.compact) {
		router.replace({
			name: "DiagramEditor",
			params: { process: props.process, diagram: name },
		});
	}
	// The watch(activeDiagramName) handles loading the new diagram XML.
}

async function onEditorReady() {
	editorReady.value = true;

	// Load the initial diagram content (fires only once on first mount)
	if (activeDiagramName.value) {
		await loadDiagramContent(activeDiagramName.value);
		hasUnsavedChanges.value = false;
	}

	hasUnsavedChanges.value = false;
	saveState.value = 'saved';
}

// Watch for diagram tab switches and load new XML without remounting the editor.
watch(activeDiagramName, async (newName) => {
	if (!newName) {
		stopHeartbeat();
		isExecutable.value = false;
		return;
	}

	startHeartbeat(newName);

	if (!editorReady.value) return;
	hasUnsavedChanges.value = false;
	saveState.value = 'saved';
	await loadDiagramContent(newName);
	hasUnsavedChanges.value = false;
});

async function loadDiagramContent(name) {
	// Check cache first
	if (diagramDataCache.value[name]) {
		if (editorRef.value) {
			await editorRef.value.loadXML(diagramDataCache.value[name]);
			if (processName.value) editorRef.value.setProcessName(processName.value);
			isExecutable.value = extractIsExecutable(diagramDataCache.value[name]);
		}
		return;
	}

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.get_process_model",
			params: { name },
		});

		const data = response.message || response;
		if (data && data.xml_content && editorRef.value) {
			diagramDataCache.value[name] = data.xml_content;
			await editorRef.value.loadXML(data.xml_content);
			if (processName.value) editorRef.value.setProcessName(processName.value);
			isExecutable.value = extractIsExecutable(data.xml_content);
		}
	} catch (error) {
		console.error("Failed to load diagram:", error);
	}
}

async function saveDiagramToCache(name) {
	if (editorRef.value) {
		const xml = await editorRef.value.getXML();
		diagramDataCache.value[name] = xml;
	}
}

function onDiagramChanged() {
	if (!editorReady.value) return;
	// Do not trigger auto-save when the process is locked
	if (!isEditable.value) return;

	hasUnsavedChanges.value = true;
	saveState.value = 'unsaved';

	clearTimeout(saveTimeout);
	hasPendingSave = true;
	saveTimeout = setTimeout(() => {
		hasPendingSave = false;
		if (activeDiagramName.value) {
			saveCurrentDiagram();
		}
	}, 1500);
}

async function saveCurrentDiagram() {
	if (!activeDiagramName.value || !editorRef.value) return;
	if (!isEditable.value) return; // Guard: process is locked

	saving.value = true;
	saveState.value = 'saving';
	try {
		const xml = await editorRef.value.getXML();
		isExecutable.value = extractIsExecutable(xml);
		const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);
		const modelName = diagram?.model_name || activeDiagramName.value;
		const description = diagram?.description || "";

		const data = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.save_process_model",
			params: {
				process: props.process,
				model_name: modelName,
				xml_content: xml,
				description: description,
			},
		});

		hasUnsavedChanges.value = false;
		diagramDataCache.value[activeDiagramName.value] = xml;

		saveState.value = 'saved';

		// Refresh the version history panel if it's open so the new snapshot shows.
		if (showVersionHistory.value) {
			versionHistoryRef.value?.load();
		}
	} catch (error) {
		console.error("Failed to save diagram:", error);
		saveState.value = 'error';
		showNotification("Error", "Failed to save: " + (error.message || error), "red");
	} finally {
		saving.value = false;
	}
}

function showNotification(title, message, theme = "green", stay = false) {
	notification.value = {
		show: true,
		title,
		message,
		theme
	};
	if (!stay) {
		// Auto-hide after 3 seconds
		setTimeout(() => {
			if (notification.value.title === title) {
				notification.value.show = false;
			}
		}, 3000);
	}
}

async function showAddDiagramDialog() {
	if (!isEditable.value) return; // Guard: process is locked
	newDiagramName.value = "";
	newDiagramDescription.value = "";
	selectedBaseVersion.value = "";

	// First map in the process → blank create. Once a map exists, the "+" flow
	// becomes "create a new version" seeded from a chosen named version.
	if (diagrams.value.length > 0) {
		newDiagramMode.value = "version";
		showNewDiagramDialog.value = true;
		await loadNamedVersionsForBase();
	} else {
		newDiagramMode.value = "blank";
		showNewDiagramDialog.value = true;
	}
}

// Load the named versions from the active map's history to offer as base
// templates for the new version.
async function loadNamedVersionsForBase() {
	loadingNamedVersions.value = true;
	namedVersions.value = [];
	try {
		const baseModel = activeDiagramName.value || (diagrams.value[0] && diagrams.value[0].name);
		if (!baseModel) return;
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_edit_history",
			params: { model_name: baseModel },
		});
		const groups = res.message || res || [];
		namedVersions.value = groups
			.filter((g) => g.is_named)
			.map((g) => ({
				name: g.head,
				version_name: g.version_name,
				timestamp: g.timestamp,
				author: g.author,
			}));
		// Pre-select the most recent named version for convenience.
		if (namedVersions.value.length) selectedBaseVersion.value = namedVersions.value[0].name;
	} catch (error) {
		console.error("Failed to load named versions:", error);
		showNotification("Error", "Failed to load named versions.", "red");
	} finally {
		loadingNamedVersions.value = false;
	}
}

function formatVersionTime(ts) {
	if (!ts) return "";
	return dayjs(ts).format("MMM D, h:mm A");
}

async function createDiagram() {
	if (!isEditable.value) return; // Guard: process is locked
	const name = newDiagramName.value.trim();
	if (!name) {
		showNotification("Name required", "Please enter a name.", "red");
		return;
	}

	// Name must be unique: different from existing process maps and from the
	// named versions it could be based on.
	const lower = name.toLowerCase();
	const dupMap = diagrams.value.some(
		(d) => (d.model_name || d.title || "").trim().toLowerCase() === lower
	);
	const dupVersion = namedVersions.value.some(
		(v) => (v.version_name || "").trim().toLowerCase() === lower
	);
	if (dupMap || dupVersion) {
		showNotification(
			"Name already used",
			"Choose a name different from existing process maps and named versions.",
			"red"
		);
		return;
	}

	creating.value = true;
	try {
		let result;
		if (newDiagramMode.value === "version") {
			if (!selectedBaseVersion.value) {
				showNotification("Select a base version", "Please choose a named version to build from.", "red");
				return;
			}
			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_map_api.create_map_from_version",
				params: {
					process: props.process,
					model_name: name,
					base_version: selectedBaseVersion.value,
					description: newDiagramDescription.value || "",
				},
			});
			result = response.message || response;
		} else {
			// Blank create — first map in the process.
			const slug = (props.process || "process").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "process";
			const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)), b => b.toString(16).padStart(2, "0")).join("");
			const processId = `${slug}_${hex}`;
			const xmlContent = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  id="Definitions_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="${processId}" isExecutable="false" />
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="${processId}" />
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;

			const response = await frappeRequest({
				url: "/api/method/one_bpmn.api.process_map_api.save_process_model",
				params: {
					process: props.process,
					model_name: name,
					xml_content: xmlContent,
					description: newDiagramDescription.value || "",
				},
			});
			result = response.message || response;
		}

		showNewDiagramDialog.value = false;

		// Reload process and open the new map.
		await loadProcess();
		selectDiagram(result.name);
	} catch (error) {
		console.error("Failed to create diagram:", error);
		showNotification("Error", "Failed to create: " + (error.message || error), "red");
	} finally {
		creating.value = false;
	}
}

async function ensureDiagramContentCached(diagramName) {
	if (diagramDataCache.value[diagramName]) {
		return diagramDataCache.value[diagramName];
	}

	const response = await frappeRequest({
		url: "/api/method/one_bpmn.api.process_map_api.get_process_model",
		params: {
			name: diagramName,
		},
	});

	const result = response.message || response;
	const xmlContent = result?.xml_content || "";

	if (xmlContent) {
		diagramDataCache.value[diagramName] = xmlContent;
	}

	return xmlContent;
}

async function handleDuplicateTab(tab) {
	if (!isEditable.value) return;
	
	const newName = `Copy of ${tab.model_name}`;
	
	// Get XML content (from editor if active, otherwise from cache/backend)
	let xmlContent;
	if (activeDiagramName.value === tab.name && editorRef.value) {
		xmlContent = await editorRef.value.getXML();
	} else {
		xmlContent = await ensureDiagramContentCached(tab.name);
	}

	if (!xmlContent) {
		showNotification("Error", "Could not read diagram content for duplication", "red");
		return;
	}

	// Generate a new unique process ID so the duplicate doesn't share the
	// original's identity (critical for import/deploy disambiguation).
	const slug = (props.process || "process").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "process";
	const hex = Array.from(crypto.getRandomValues(new Uint8Array(4)), b => b.toString(16).padStart(2, "0")).join("");
	const newProcessId = `${slug}_${hex}`;

	// Replace the old process id in the XML:
	//   <bpmn:process id="OLD_ID" ...>  →  <bpmn:process id="NEW_ID" ...>
	//   bpmnElement="OLD_ID"            →  bpmnElement="NEW_ID"
	const processIdMatch = xmlContent.match(/<bpmn:process\s[^>]*id=["']([^"']+)["']/);
	if (processIdMatch) {
		const oldId = processIdMatch[1];
		xmlContent = xmlContent.replaceAll(oldId, newProcessId);
	}

	creating.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.save_process_model",
			params: {
				process: props.process,
				model_name: newName,
				xml_content: xmlContent,
				description: tab.description || "",
			},
		});

		const result = response.message || response;
		await loadProcess();
		selectDiagram(result.name);
		showNotification("Success", `Diagram duplicated as "${newName}"`, "green");
	} catch (error) {
		console.error("Duplication failed:", error);
		showNotification("Error", "Failed to duplicate diagram: " + (error.message || error), "red");
	} finally {
		creating.value = false;
	}
}

async function handleDeleteTab(tab) {
	if (!isEditable.value) return;
	if (!confirm(`Are you sure you want to delete "${tab.model_name}"? This action cannot be undone.`)) return;

	// ── Optimistic: remove from UI immediately ───────────────────────
	const tabIndex = openTabs.value.findIndex(t => t.name === tab.name);
	const diagramIndex = diagrams.value.findIndex(d => d.name === tab.name);
	const removedTab = tabIndex > -1 ? openTabs.value.splice(tabIndex, 1)[0] : null;
	const removedDiagram = diagramIndex > -1 ? diagrams.value.splice(diagramIndex, 1)[0] : null;
	delete diagramDataCache.value[tab.name];

	// Switch active tab if the deleted tab was active
	const wasActive = activeDiagramName.value === tab.name;
	if (wasActive) {
		// Clear unsaved state so selectDiagram doesn't try to save the deleted diagram
		clearTimeout(saveTimeout);
		hasPendingSave = false;
		hasUnsavedChanges.value = false;
		saveState.value = "idle";

		if (openTabs.value.length > 0) {
			selectDiagram(openTabs.value[Math.min(tabIndex, openTabs.value.length - 1)].name);
		} else if (diagrams.value.length > 0) {
			selectDiagram(diagrams.value[0].name);
		} else {
			activeDiagramName.value = null;
			router.replace({ name: "ProcessEditor", params: { process: props.process } });
		}
	}

	// ── Show notification immediately (optimistic) ──────────────────
	showNotification("Deleted", `Diagram "${tab.model_name}" has been deleted`, "green");

	// ── Server call (no loadProcess round-trip) ──────────────────────
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.delete_diagram",
			params: { name: tab.name },
		});
	} catch (error) {
		// ── Rollback on failure ─────────────────────────────────────
		console.error("Deletion failed:", error);
		if (removedDiagram) diagrams.value.splice(diagramIndex, 0, removedDiagram);
		if (removedTab) openTabs.value.splice(tabIndex, 0, removedTab);
		showNotification("Error", "Failed to delete diagram: " + (error.message || error), "red");
	}
}

async function closeTab(name) {
	// If closing the active tab with pending changes, save silently first
	if (activeDiagramName.value === name && isUnsavedOrInFlight()) {
		clearTimeout(saveTimeout);
		hasPendingSave = false;
		await saveCurrentDiagram();
	}

	const index = openTabs.value.findIndex((t) => t.name === name);
	if (index > -1) {
		openTabs.value.splice(index, 1);

		// If closing active tab, switch to another
		if (activeDiagramName.value === name) {
			if (openTabs.value.length > 0) {
				const newIndex = Math.min(index, openTabs.value.length - 1);
				selectDiagram(openTabs.value[newIndex].name);
			} else {
				activeDiagramName.value = null;
			}
		}
	}
}

/**
 * Apply field updates to matching entries in both diagrams and openTabs.
 * Keeps the update/revert logic in one place (Review #2).
 */
function applyTabDiagramFields(matchName, fields) {
	const diagramEntry = diagrams.value.find((d) => d.name === matchName);
	const tabEntry = openTabs.value.find((t) => t.name === matchName);
	if (diagramEntry) Object.assign(diagramEntry, fields);
	if (tabEntry) Object.assign(tabEntry, fields);
}

async function renameProcessModel({ tabName, oldModelName, newModelName }) {
	if (!isEditable.value) return; // Guard: process is locked
	// Cancel the debounce timer so autosave can't fire with a stale model_name.
	clearTimeout(saveTimeout);
	hasPendingSave = false;

	// If there are unsaved diagram changes, flush them under the OLD name first.
	if (hasUnsavedChanges.value && activeDiagramName.value === tabName && editorRef.value) {
		await saveCurrentDiagram();
	}

	// ── Optimistic: show new name + notification immediately ─────────
	applyTabDiagramFields(tabName, { model_name: newModelName, title: newModelName });
	showNotification("Renamed", `Diagram renamed to "${newModelName}"`, "green");

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.rename_process_model",
			params: {
				name: tabName,
				new_title: newModelName,
			},
		});

		const result = response.message || response;
		const newName = result.name;
		const actualModelName = result.model_name;

		// Transfer cached XML to new key (name changes because autoname = field:title)
		if (diagramDataCache.value[tabName]) {
			diagramDataCache.value[newName] = diagramDataCache.value[tabName];
			if (newName !== tabName) {
				delete diagramDataCache.value[tabName];
			}
		}

		// Confirm server-side name + display fields
		applyTabDiagramFields(tabName, {
			name: newName,
			model_name: actualModelName,
			title: actualModelName,
		});

		// Update active diagram ref and URL if the renamed tab is active
		if (activeDiagramName.value === tabName) {
			activeDiagramName.value = newName;
			router.replace({
				name: "DiagramEditor",
				params: { process: props.process, diagram: newName },
			});
		}
	} catch (error) {
		// ── Rollback on failure ─────────────────────────────────────
		console.error("Failed to rename process model:", error);
		applyTabDiagramFields(tabName, { model_name: oldModelName, title: oldModelName });
		showNotification(
			"Rename Failed",
			error.message || error._server_messages || "An error occurred while renaming.",
			"red"
		);
	}
}

function goBack() {
	router.push({ name: "Home" });
}

// ── Version Comparison (Diff) ──

// Deployed-version compare (legacy picker, kept available).
function openVersionPicker() {
	if (!versionDiffRef.value) return;

	versionDiffRef.value.open(getCurrentDiagramXml);
}

// Shared getter for the current canvas XML.
async function getCurrentDiagramXml() {
	if (editorRef.value) {
		return await editorRef.value.getXML();
	}
	return diagramDataCache.value[activeDiagramName.value] || null;
}

// Google-Docs-style save-history side panel.
function toggleVersionHistory() {
	if (!activeDiagramName.value) return;
	showVersionHistory.value = !showVersionHistory.value;
}

// Restore: load the restored XML back onto the canvas and persist.
async function onVersionRestored({ xml }) {
	if (!xml || !editorRef.value) return;
	try {
		await editorRef.value.loadXML(xml);
		diagramDataCache.value[activeDiagramName.value] = xml;
		isExecutable.value = extractIsExecutable(xml);
		hasUnsavedChanges.value = false;
		saveState.value = 'saved';
		showNotification("Restored", "The selected version is now the current diagram.", "green");
	} catch (error) {
		console.error("Failed to load restored XML:", error);
		showNotification("Error", "Restored on the server, but failed to load onto the canvas. Reload the page.", "red");
	}
}

async function exportCurrentDiagram() {
	if (!activeDiagramName.value || !editorRef.value) return;

	try {
		const xml = await editorRef.value.getXML();
		const diagram = diagrams.value.find((d) => d.name === activeDiagramName.value);
		const title = diagram?.model_name || activeDiagramName.value;

		// Check if diagram references any config records
		try {
			const resp = await frappeRequest({
				url: "/api/method/one_bpmn.api.config_export_import.export_bpmn_config",
				params: { xml_content: xml },
			});
			const data = resp.message || resp;
			const counts = data.counts || {};
			const total = (counts.server_scripts || 0) + (counts.workflow_states || 0) + (counts.workflow_action_masters || 0);

			if (total > 0) {
				// Has config records → show popup
				pendingExportXml = xml;
				pendingExportTitle = title;
				exportConfigCounts.value = counts;
				showExportConfigDialog.value = true;
				return;
			}
		} catch (e) {
			// If config check fails, just export BPMN only
			console.warn("Config export check failed, exporting BPMN only:", e);
		}

		// No config records or check failed — export BPMN directly
		const filename = downloadBpmn(xml, title);
		showNotification("Exported", `Downloaded as ${filename}`, "green");
	} catch (error) {
		console.error("Failed to export diagram:", error);
		showNotification("Error", "Failed to export diagram", "red");
	}
}

// Export BPMN only (from ExportConfigDialog)
function doExportBpmnOnly() {
	if (pendingExportXml) {
		const filename = downloadBpmn(pendingExportXml, pendingExportTitle);
		showNotification("Exported", `Downloaded as ${filename}`, "green");
		pendingExportXml = "";
		pendingExportTitle = "";
	}
}

// Export BPMN + Config JSON (from ExportConfigDialog)
async function doExportWithConfig(selected) {
	if (!pendingExportXml) return;

	// 1. Download BPMN
	const bpmnFilename = downloadBpmn(pendingExportXml, pendingExportTitle);

	// 2. Fetch full config data and download as JSON
	try {
		const resp = await frappeRequest({
			url: "/api/method/one_bpmn.api.config_export_import.export_bpmn_config",
			params: { xml_content: pendingExportXml },
		});
		const data = resp.message || resp;

		// Filter by user selection
		const filteredData = {
			export_metadata: data.export_metadata,
			server_scripts: selected.server_scripts ? data.server_scripts : [],
			workflow_states: selected.workflow_states ? data.workflow_states : [],
			workflow_action_masters: selected.workflow_action_masters ? data.workflow_action_masters : [],
		};

		const jsonStr = JSON.stringify(filteredData, null, 2);
		const jsonFilename = sanitiseFilename(pendingExportTitle) + "-config.json";
		const blob = new Blob([jsonStr], { type: "application/json" });
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = jsonFilename;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);

		showNotification(
			"Exported",
			`Downloaded ${bpmnFilename} and ${jsonFilename}`,
			"green"
		);
	} catch (error) {
		console.error("Failed to export config:", error);
		showNotification("Export", `Downloaded ${bpmnFilename} but config export failed`, "yellow");
	}

	pendingExportXml = "";
	pendingExportTitle = "";
}

function triggerImport() {
	if (importFileInput.value) {
		// Reset so the same file can be re-imported
		importFileInput.value.value = "";
		importFileInput.value.click();
	}
}

function triggerImportConfig() {
	if (importConfigFileInput.value) {
		importConfigFileInput.value.value = "";
		importConfigFileInput.value.click();
	}
}

async function handleImportConfigFile(event) {
	const file = event.target.files && event.target.files[0];
	if (!file) return;

	configImporting.value = true;
	showConfigImportResults.value = true;
	configImportResults.value = { created: [], skipped: [], needs_confirmation: [] };

	try {
		const jsonText = await new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = (e) => resolve(e.target.result);
			reader.onerror = () => reject(new Error("Failed to read file"));
			reader.readAsText(file);
		});

		const resp = await frappeRequest({
			url: "/api/method/one_bpmn.api.config_export_import.import_bpmn_config",
			method: "POST",
			params: { config_json: jsonText },
		});

		configImportResults.value = resp.message || resp;
	} catch (error) {
		console.error("Config import failed:", error);
		showConfigImportResults.value = false;
		showNotification(
			"Import Failed",
			error.message || "An unexpected error occurred while importing config.",
			"red"
		);
	} finally {
		configImporting.value = false;
	}
}

async function handleImportFile(event) {
	const file = event.target.files && event.target.files[0];
	if (!file) return;

	importing.value = true;
	try {
		// Read the file as text
		const xmlContent = await new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = (e) => resolve(e.target.result);
			reader.onerror = () => reject(new Error("Failed to read file"));
			reader.readAsText(file);
		});

		// Call the backend import endpoint via frappeRequest for consistent
		// CSRF handling, response parsing, and error surfacing.
		const result = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.import_bpmn",
			method: "POST",
			params: {
				xml_content: xmlContent,
				// Use the filename (minus .bpmn) as the human-readable title
				title: file.name.replace(/\.bpmn$/i, ""),
				process: props.process || undefined,
			},
		});

		const action = result.action === "updated" ? "updated" : "imported";

		// Pre-populate cache so the watch(activeDiagramName) handler
		// gets an instant cache-hit and calls loadXML without a round-trip.
		diagramDataCache.value[result.name] = xmlContent;

		// Reload process diagrams to sync the diagrams list
		await loadProcess();
		let diagramEntry = diagrams.value.find((d) => d.name === result.name);
		if (!diagramEntry) {
			// Not in the process-scoped list — add a synthetic entry so the tab appears
			diagramEntry = {
				name: result.name,
				model_name: result.model_name,
				title: result.model_name,
				process_id: result.process_id,
				is_active: 0,
				status: "Inactive",
			};
			diagrams.value.push(diagramEntry);
		}

		// Preserve existing openTabs; only add the imported diagram tab if not already open
		if (!openTabs.value.some((tab) => tab.name === diagramEntry.name)) {
			openTabs.value = [...openTabs.value, diagramEntry];
		}

		// Switch to the imported diagram via SPA (no page reload → no Preact crash)
		// The watch(activeDiagramName) picks up the change and calls loadDiagramContent.
		activeDiagramName.value = result.name;
		router.replace({
			name: "DiagramEditor",
			params: { process: props.process, diagram: result.name },
		});

		showNotification(
			"Import Successful",
			`Diagram "${result.model_name}" ${action} successfully.`,
			"green"
		);

		// Run readiness check (informational — does not block)
		await runReadinessCheck(xmlContent, "import");
	} catch (error) {
		console.error("Import failed:", error);
		showNotification(
			"Import Failed",
			error.message || "An unexpected error occurred while importing.",
			"red"
		);
	} finally {
		importing.value = false;
	}
}

function getStatusTheme(status) {
	switch (status) {
		case "Active":
			return "green";
		case "Inactive":
			return "orange";
		default:
			return "gray";
	}
}

// Avatar Helpers
function getInitials(fullName) {
	if (!fullName) return "U";
	const names = fullName.trim().split(/\s+/);
	if (names.length === 1) return names[0].charAt(0).toUpperCase();
	return (names[0].charAt(0) + names[names.length - 1].charAt(0)).toUpperCase();
}

const AVATAR_COLORS = [
	"bg-red-500", "bg-orange-500", "bg-amber-500", "bg-yellow-500",
	"bg-lime-500", "bg-green-500", "bg-emerald-500", "bg-teal-500",
	"bg-cyan-500", "bg-sky-500", "bg-blue-500", "bg-indigo-500",
	"bg-violet-500", "bg-purple-500", "bg-fuchsia-500", "bg-pink-500",
	"bg-rose-500",
];

function getAvatarColor(userName) {
	if (!userName) return "bg-gray-400";
	let hash = 0;
	for (let i = 0; i < userName.length; i++) {
		hash = userName.charCodeAt(i) + ((hash << 5) - hash);
	}
	const colorIndex = Math.abs(hash) % AVATAR_COLORS.length;
	return AVATAR_COLORS[colorIndex];
}

// --- DMN Editor Handlers ---

async function onLaunchDmnEditor(event) {
	const element = event.element;
	if (!element) {
		console.error("[DMN] No element found for DMN editor launch — is a Business Rule Task selected?");
		return;
	}

	// Resolve which decision to load:
	// 1. calledDecisionId from the element's extension attribute (set by dropdown picker)
	// 2. event.value passed from the properties panel
	// 3. Fall back to the element's own ID
	const bo = element.businessObject;
	const calledDecisionId = (bo && bo.get("spiffworkflow:calledDecisionId")) || event.value || "";
	const decisionId = calledDecisionId || element.id;
	const elementName = bo?.name || decisionId || "Decision Model";

	activeDmnElement = element;
	activeDmnEventBus = event.eventBus;
	activeDmnDecisionId = decisionId;
	dmnEditorTitle.value = `Edit Decision Model — ${elementName}`;

	console.log(`[DMN] Launching editor for element: ${element.id}, decision: ${decisionId}, model: ${activeDiagramName.value}`);

	// Load stored XML from backend
	let storedXml = "";
	if (activeDiagramName.value) {
		try {
			const resp = await frappeRequest({
				url: "/api/method/one_bpmn.api.dmn_api.get_dmn_xml",
				params: {
					process_model: activeDiagramName.value,
					decision_id: decisionId,
				},
			});
			// frappeRequest unwraps the "message" key automatically.
			// get_dmn_xml returns a plain string; handle both wrapped and raw.
			if (typeof resp === "string") {
				storedXml = resp;
			} else if (resp && typeof resp.message === "string") {
				storedXml = resp.message;
			}
			console.log(`[DMN] Loaded stored XML: ${storedXml ? storedXml.length + " chars" : "(empty)"}`);
		} catch (err) {
			console.warn("[DMN] Could not load stored XML:", err);
		}
	}

	dmnEditorXml.value = storedXml;
	dmnEditorKey.value++;          // Force a fresh DmnEditor instance
	showDmnEditorDialog.value = true;
}

async function onDmnXmlChanged(xml) {
	// Autosave: persist every debounced change to the backend
	if (!xml) {
		console.warn("[DMN] onDmnXmlChanged called with empty XML — skipping save");
		return;
	}
	if (!activeDmnElement) {
		console.warn("[DMN] onDmnXmlChanged: no activeDmnElement — skipping save");
		return;
	}
	if (!activeDiagramName.value) {
		console.warn("[DMN] onDmnXmlChanged: no activeDiagramName — skipping save");
		return;
	}

	const decisionId = activeDmnDecisionId || activeDmnElement.id;
	const elementName = activeDmnElement.businessObject?.name || decisionId;

	console.log(`[DMN] Saving DMN XML for decision: ${decisionId}, model: ${activeDiagramName.value}, xml length: ${xml.length}`);

	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.dmn_api.save_dmn_xml",
			method: "POST",
			params: {
				process_model: activeDiagramName.value,
				decision_id: decisionId,
				decision_name: elementName,
				dmn_xml: xml,
			},
		});
		console.log("[DMN] ✅ Save successful");
	} catch (err) {
		console.error("[DMN] Autosave failed:", err);
	}

	// Write DMN reference back to the BPMN element
	if (activeDmnEventBus && activeDmnElement) {
		activeDmnEventBus.fire("spiff.dmn.edit.update", {
			element: activeDmnElement,
			value: elementId,
		});
	}
}

function closeDmnEditor() {
	showDmnEditorDialog.value = false;
	activeDmnElement = null;
	activeDmnEventBus = null;
}

// --- SpiffWorkflow Editor Handlers ---

function onLaunchScriptEditor(event) {
	activeScriptEvent = event;

	logixElement.value = event.element;
	logixScriptType.value = event.scriptType || "bpmn:script";
	logixCurrentScript.value = event.script || "";
	logixEventBus.value = event.eventBus;
	logixProcessContext.value = extractProcessContext(event.element);

	// Prep dialog state so it's ready if the user goes back from Logix
	const typeLabels = {
		"bpmn:script": "Link Server Script",
		"spiffworkflow:PreScript": "Link Pre-Script to Server Script",
		"spiffworkflow:PostScript": "Link Post-Script to Server Script",
	};
	scriptEditorTitle.value = typeLabels[event.scriptType] || "Link Server Script";
	linkedScriptName.value = event.script || "";
	previewScriptContent.value = null;
	loadingPreview.value = false;
	editScriptContent.value = "";
	editScriptMeta.value = { script_type: "", reference_doctype: "" };
	scriptDialogMode.value = event.script ? "edit" : "select";
	serverScriptSearch.value = "";
	selectedServerScript.value = event.script || null;
	isScriptTaskElement.value = !!(event.element?.type === "bpmn:ScriptTask");
	if (event.script) loadScriptContent(event.script, "edit");

	// Go straight to Logix canvas — skip the script selector dialog
	showLogixCanvas.value = true;

	// Load server scripts in the background so the dialog is ready if user clicks back
	loadServerScriptsInBackground();
}

async function loadServerScriptsInBackground() {
	if (serverScripts.value.length) return;
	loadingScripts.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "Server Script",
				fields: ["name", "script_type", "reference_doctype", "disabled", "module", "modified"],
				limit_page_length: 0,
				order_by: "modified desc",
			},
		});
		const data = response.message || response;
		serverScripts.value = Array.isArray(data) ? data : [];
	} catch (e) {
		console.error("Failed to load server scripts:", e);
	} finally {
		loadingScripts.value = false;
	}
}

function openLogixCanvas() {
	showScriptEditorDialog.value = false;
	showLogixCanvas.value = true;
}

function onLogixBack() {
	showLogixCanvas.value = false;
	showScriptEditorDialog.value = true;
}

function onLogixScriptSaved(scriptName) {
	if (activeScriptEvent && activeScriptEvent.eventBus && scriptName) {
		activeScriptEvent.eventBus.fire("spiff.script.update", {
			element: activeScriptEvent.element,
			scriptType: activeScriptEvent.scriptType,
			script: scriptName,
		});
	}
}

function saveScript() {
	if (activeScriptEvent && activeScriptEvent.eventBus && selectedServerScript.value) {
		activeScriptEvent.eventBus.fire("spiff.script.update", {
			element: activeScriptEvent.element,
			scriptType: activeScriptEvent.scriptType,
			script: selectedServerScript.value,
		});
	}
	showScriptEditorDialog.value = false;
	activeScriptEvent = null;
}

async function createAndLinkScript() {
	if (!newScript.value.name || !newScript.value.script_type || !newScript.value.script) {
		showNotification("Validation", "Script name, type, and content are required.", "red");
		return;
	}

	creatingScript.value = true;
	try {
		const result = await frappeRequest({
			url: "one_bpmn.api.server_script_api.create_server_script",
			params: {
				script_name: newScript.value.name,
				script_type: newScript.value.script_type,
				script: newScript.value.script,
				...(newScript.value.reference_doctype && { reference_doctype: newScript.value.reference_doctype }),
				...(newScript.value.doctype_event && { doctype_event: newScript.value.doctype_event }),
				...(newScript.value.api_method && { api_method: newScript.value.api_method }),
				...(newScript.value.allow_guest && { allow_guest: 1 }),
				...(newScript.value.event_frequency && { event_frequency: newScript.value.event_frequency }),
				...(newScript.value.cron_format && { cron_format: newScript.value.cron_format }),
				...(newScript.value.module && { module: newScript.value.module }),
			},
		});

		if (activeScriptEvent && activeScriptEvent.eventBus) {
			activeScriptEvent.eventBus.fire("spiff.script.update", {
				element: activeScriptEvent.element,
				scriptType: activeScriptEvent.scriptType,
				script: result.name,
			});
		}
		showNotification("Success", `Server Script "${result.name}" created and linked.`, "green");
		showScriptEditorDialog.value = false;
		activeScriptEvent = null;
	} catch (error) {
		console.error("Failed to create server script:", error);
		showNotification("Error", "Failed to create: " + (error.message || error), "red");
	} finally {
		creatingScript.value = false;
	}
}

async function toggleScriptStatus(script) {
	const newDisabledStatus = script.disabled ? 0 : 1;
	try {
		await frappeRequest({
			url: "one_bpmn.api.server_script_api.toggle_server_script",
			params: {
				script_name: script.name,
				disabled: newDisabledStatus,
			},
		});
		script.disabled = newDisabledStatus;
	} catch (error) {
		console.error("Failed to toggle server script status:", error);
	}
}

async function loadScriptContent(scriptName, target) {
	if (!scriptName) return;
	if (target === "preview") {
		loadingPreview.value = true;
		previewScriptContent.value = null;
	} else {
		loadingEditScript.value = true;
	}
	try {
		const response = await frappeRequest({
			url: "/api/method/frappe.client.get",
			params: {
				doctype: "Server Script",
				name: scriptName,
			},
		});
		const doc = response.message || response;
		if (target === "preview") {
			previewScriptContent.value = doc.script || "# (empty script)";
		} else {
			editScriptContent.value = doc.script || "";
			editScriptMeta.value = {
				script_type: doc.script_type || "",
				reference_doctype: doc.reference_doctype || "",
			};
		}
	} catch (error) {
		console.error(`Failed to load script "${scriptName}":`, error);
		if (target === "preview") {
			previewScriptContent.value = "# Failed to load script content";
		}
	} finally {
		if (target === "preview") {
			loadingPreview.value = false;
		} else {
			loadingEditScript.value = false;
		}
	}
}

async function saveEditedScript() {
	if (!linkedScriptName.value || !editScriptContent.value) return;
	savingEditScript.value = true;
	try {
		await frappeRequest({
			url: "/api/method/frappe.client.set_value",
			params: {
				doctype: "Server Script",
				name: linkedScriptName.value,
				fieldname: "script",
				value: editScriptContent.value,
			},
		});
		showNotification("Success", `Script "${linkedScriptName.value}" updated.`, "green");
		showScriptEditorDialog.value = false;
		activeScriptEvent = null;
	} catch (error) {
		console.error("Failed to save script:", error);
		showNotification("Error", "Failed to save: " + (error.message || error), "red");
	} finally {
		savingEditScript.value = false;
	}
}

watch(selectedServerScript, (newVal) => {
	if (newVal && scriptDialogMode.value === "select") {
		loadScriptContent(newVal, "preview");
	} else {
		previewScriptContent.value = null;
	}
});

// --- Delete with Script Confirmation ---

function onConfirmScriptDelete(payload) {
	// payload: { elements, scriptNames, usageMap, doDelete }
	pendingDeleteElements = payload.elements;
	pendingDeleteModeling = payload.doDelete; // the original removeElements fn
	deleteScriptConfirmData.value = {
		elements: payload.elements,
		scriptNames: payload.scriptNames,
		usageMap: payload.usageMap,
	};
	showDeleteScriptConfirm.value = true;
}

async function confirmDeleteElement(alsoDeleteScript) {
	showDeleteScriptConfirm.value = false;
	if (alsoDeleteScript) {
		for (const scriptName of deleteScriptConfirmData.value.scriptNames) {
			try {
				await frappeRequest({
					url: "frappe.client.delete",
					params: { doctype: "Server Script", name: scriptName },
				});
			} catch (e) {
				console.error("Failed to delete script:", scriptName, e);
			}
		}
	}
	// Call the original (pre-intercept) removeElements directly
	if (pendingDeleteModeling && pendingDeleteElements) {
		pendingDeleteModeling(pendingDeleteElements);
	}
	pendingDeleteElements = null;
	pendingDeleteModeling = null;
}

// --- Notification Dialog Handlers (Send Task) ---

// Notification editor launch handler delegates to composable
function onLaunchNotificationEditor(event) {
	notifDialog.openDialog(event);
}

// --- Notify Assignee Editor (User Task) ---
const showNotifyAssigneeDialog = ref(false);
const notifyAssigneeBody = ref("");
const notifyAssigneeSubject = ref("");
const notifyAssigneeTemplate = ref("");
let notifyAssigneeEvent = null;

watch(showNotifyAssigneeDialog, (isOpen) => {
	if (!isOpen) {
		notifyAssigneeEvent = null;
		notifyAssigneeBody.value = "";
		notifyAssigneeSubject.value = "";
		notifyAssigneeTemplate.value = "";
	}
});
function onLaunchNotifyAssigneeEditor(event) {
	notifyAssigneeEvent = event;
	notifyAssigneeBody.value = event.body || "";
	notifyAssigneeSubject.value = event.subject || "";
	notifyAssigneeTemplate.value = event.template || "";
	showNotifyAssigneeDialog.value = true;
}

function onSaveNotifyAssigneeBody(payload) {
	const { body = "", subject = "", template = "" } = payload || {};
	// Auto-save fires this repeatedly — keep notifyAssigneeEvent alive until the
	// dialog closes (the showNotifyAssigneeDialog watcher clears it).
	if (notifyAssigneeEvent && notifyAssigneeEvent.eventBus) {
		notifyAssigneeEvent.eventBus.fire("spiff.userTask.notifyAssignee.update", {
			element: notifyAssigneeEvent.element,
			body,
			subject,
			template,
		});
	}
}

function onLaunchMarkdownEditor(event) {
	activeMarkdownEvent = event;
	markdownEditorContent.value = event.value || "";
	showMarkdownEditorDialog.value = true;
}

function saveMarkdown() {
	if (activeMarkdownEvent && activeMarkdownEvent.eventBus) {
		activeMarkdownEvent.eventBus.fire("spiff.markdown.update", {
			element: activeMarkdownEvent.element,
			value: markdownEditorContent.value,
		});
	}
	showMarkdownEditorDialog.value = false;
	activeMarkdownEvent = null;
}

async function onLaunchCallActivityEditor(event) {
	if (!event.processId) {
		showNotification(
			"Call Activity",
			"No process linked. Use the Search button to select a process first.",
			"orange"
		);
		return;
	}

	try {
		// Use the dedicated resolve endpoint — returns one record without
		// fetching the entire model list client-side.
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.process_map_api.resolve_process_model_by_id",
			params: { process_id: event.processId },
		});
		const linked = response.message || response;

		if (linked && linked.name) {
			// Build URL with encoded segments to handle spaces and reserved chars
			const base = linked.process_name
				? `/processa/process/${encodeURIComponent(linked.process_name)}/diagram/${encodeURIComponent(linked.name)}`
				: `/processa/process/${encodeURIComponent(linked.name)}`;
			// noopener,noreferrer prevents reverse-tabnabbing via window.opener
			window.open(base, "_blank", "noopener,noreferrer");
		} else {
			showNotification(
				"Call Activity",
				`Linked process "${event.processId}" not found in this system.`,
				"orange"
			);
		}
	} catch (err) {
		showNotification("Call Activity", "Failed to look up linked process.", "red");
	}
}

function onLaunchCallActivitySearch(event) {
	callActivitySearchEvent = event;
	showCallActivitySearchDialog.value = true;
}

function onCallActivitySelected(processId) {
	const event = callActivitySearchEvent;
	if (!event) return;

	// Primary: drive the update directly via the modeler's command stack.
	// Reliable regardless of SpiffWorkflow's async once-listener state.
	if (editorRef.value && typeof editorRef.value.updateCalledElement === "function") {
		editorRef.value.updateCalledElement(event.element, processId);
	}

	// Secondary: also fire spiff.callactivity.update so the once-listener (if still
	// active) can run its own commandStack path.
	if (event.eventBus) {
		event.eventBus.fire("spiff.callactivity.update", {
			element: event.element,
			value: processId,
		});
	}

	showCallActivitySearchDialog.value = false;
	callActivitySearchEvent = null;
}



function onCancelCallActivitySearch() {
	// Mirror the select path: close dialog AND clear the stored event reference
	// so we don't retain stale BPMN element/eventBus objects.
	showCallActivitySearchDialog.value = false;
	callActivitySearchEvent = null;
}
function toggleComments() {
	if (editorRef.value?.toggleTimeline) {
		editorRef.value.toggleTimeline();
	}
}

const totalCommentCount = computed(() => {
	return editorRef.value?.comments?.length || 0;
});
</script>

<style scoped>
/* Fix dark background on form inputs in dialog */
:deep(.dialog-form input),
:deep(.dialog-form textarea),
:deep(.dialog-body input[type="text"]),
:deep(.dialog-body textarea) {
	background-color: white !important;
	color: #1f2937 !important;
}

/* Force TextEditor to fill full dialog width */
:deep(.ProseMirror) {
	max-width: 100% !important;
	width: 100% !important;
}

:deep(.tiptap) {
	max-width: 100% !important;
	width: 100% !important;
}

/* Logix AI Assistant — wider than the standard 7xl cap */
:deep(.dialog-content:has(.lc-root)) {
	max-width: min(92vw, 1520px) !important;
	width: min(92vw, 1520px) !important;
}

/* DMN Editor Dialog — near-full-screen experience */
:deep(.dialog-content:has(.dmn-dialog-body)) {
	max-width: min(92vw, 1520px) !important;
	width: min(92vw, 1520px) !important;
}

.dmn-dialog-body {
	height: 70vh;
	min-height: 500px;
	display: flex;
	flex-direction: column;
	padding: 0 !important;
	overflow: hidden;
}

.scrollbar-hide::-webkit-scrollbar {
	display: none;
}
.scrollbar-hide {
	-ms-overflow-style: none;
	scrollbar-width: none;
}
</style>
