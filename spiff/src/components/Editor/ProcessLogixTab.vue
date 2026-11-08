<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import LogixCanvas from "@/components/Logix/LogixCanvas.vue";
import { PROCESS_KEY } from "@/composables/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	confirmDeleteElement,
	createAndLinkScript,
	creatingScript,
	deleteScriptConfirmData,
	doctypeEvents,
	doctypeSearch,
	editScriptContent,
	editScriptMeta,
	eventFrequencies,
	filteredDoctypeOptions,
	filteredModuleOptions,
	filteredServerScripts,
	linkedScriptName,
	loadingEditScript,
	loadingPreview,
	loadingScripts,
	logixCurrentScript,
	logixElement,
	logixEventBus,
	logixProcessContext,
	logixReadonly,
	logixScriptType,
	moduleSearch,
	newScript,
	onLogixBack,
	onLogixScriptSaved,
	openLogixCanvas,
	previewScriptContent,
	saveEditedScript,
	saveScript,
	savingEditScript,
	scriptDialogMode,
	scriptEditorTitle,
	selectedServerScript,
	serverScriptSearch,
	setTimeout,
	showDeleteScriptConfirm,
	showDoctypeDropdown,
	showLogixCanvas,
	showModuleDropdown,
	showScriptEditorDialog,
} = pc;
</script>

<template>
	<!-- Server Script Selector/Creator Dialog -->
	<Dialog v-model="showScriptEditorDialog" :options="{ title: scriptEditorTitle, size: '5xl' }">
		<template #body-content>
			<div class="space-y-4">
				<!-- Mode Tabs -->
				<div class="flex border-b border-gray-200">
					<button
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
							scriptDialogMode === 'select'
								? 'border-blue-500 text-blue-600'
								: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
						]"
						@click="scriptDialogMode = 'select'"
					>
						<Icon icon="lucide:search" class="w-4 h-4 inline mr-1.5" />Select Existing
					</button>
					<button
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
							scriptDialogMode === 'create'
								? 'border-blue-500 text-blue-600'
								: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
						]"
						@click="scriptDialogMode = 'create'"
					>
						<Icon icon="lucide:plus" class="w-4 h-4 inline mr-1.5" />Create New
					</button>
					<button
						v-if="linkedScriptName"
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
							scriptDialogMode === 'edit'
								? 'border-blue-500 text-blue-600'
								: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
						]"
						@click="scriptDialogMode = 'edit'"
					>
						<Icon icon="lucide:pencil" class="w-4 h-4 inline mr-1.5" />Edit
					</button>
					<button
						:class="[
							'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
						]"
						@click="openLogixCanvas"
					>
						<Icon icon="lucide:bot" class="w-4 h-4 inline mr-1.5" />Logix Chat
					</button>
				</div>

				<!-- Select Existing Mode -->
				<div v-if="scriptDialogMode === 'select'" class="space-y-3">
					<div class="text-sm text-gray-500">
						Search and select an existing Server Script to link.
					</div>
					<div class="relative">
						<Icon
							icon="lucide:search"
							class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
						/>
						<input
							v-model="serverScriptSearch"
							type="text"
							placeholder="Search server scripts..."
							class="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
						/>
					</div>
					<div class="max-h-72 overflow-y-auto border border-gray-200 rounded-lg">
						<div v-if="loadingScripts" class="p-6 text-center text-gray-400">
							<div
								class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"
							></div>
							Loading scripts...
						</div>
						<div
							v-else-if="filteredServerScripts.length === 0"
							class="p-6 text-center text-gray-400"
						>
							No server scripts found.
						</div>
						<div v-else>
							<template v-for="script in filteredServerScripts" :key="script.name">
								<div
									:class="[
										'flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors',
										selectedServerScript === script.name
											? 'bg-blue-50 border-l-4 border-l-blue-500'
											: 'hover:bg-gray-50',
									]"
									@click="selectedServerScript = script.name"
								>
									<div>
										<div class="text-sm font-medium text-gray-900">
											{{ script.name }}
										</div>
										<div class="text-xs text-gray-500 mt-0.5">
											{{ script.script_type
											}}<span v-if="script.reference_doctype">
												· {{ script.reference_doctype }}</span
											>
										</div>
									</div>
									<div class="flex items-center">
										<Icon
											v-if="selectedServerScript === script.name"
											icon="lucide:check-circle"
											class="w-5 h-5 text-blue-500"
										/>
									</div>
								</div>
								<div
									v-if="
										selectedServerScript === script.name &&
										previewScriptContent !== null
									"
									class="border-b border-gray-100 bg-gray-50/50"
								>
									<div
										v-if="loadingPreview"
										class="px-4 py-3 text-center text-gray-400 text-sm"
									>
										<div
											class="animate-spin rounded-full h-5 w-5 border-b-2 border-gray-400 mx-auto mb-1"
										></div>
										Loading...
									</div>
									<pre
										v-else
										class="px-4 py-3 text-[13px] font-mono text-gray-700 overflow-x-auto max-h-48 whitespace-pre-wrap"
										>{{ previewScriptContent }}</pre>
								</div>
							</template>
						</div>
					</div>
				</div>

				<!-- Create New Mode -->
				<div v-else-if="scriptDialogMode === 'create'" class="space-y-4">
					<div class="text-sm text-gray-500">
						Create a new Server Script and link it to this element.
					</div>
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>Script Name <span class="text-red-500">*</span></label
							>
							<input
								v-model="newScript.name"
								type="text"
								placeholder="e.g. Validate Employee Shift"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
							/>
						</div>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>Script Type <span class="text-red-500">*</span></label
							>
							<select
								v-model="newScript.script_type"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								disabled
							>
								<option value="API">API</option>
							</select>
						</div>
					</div>
					<div
						v-if="
							['DocType Event', 'Permission Query'].includes(newScript.script_type)
						"
						class="grid grid-cols-2 gap-4"
					>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>Reference DocType</label
							>
							<div class="relative">
								<input
									v-model="doctypeSearch"
									type="text"
									:placeholder="
										newScript.reference_doctype || 'Search DocType...'
									"
									class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
									@focus="
										showDoctypeDropdown = true;
										showModuleDropdown = false;
										doctypeSearch = '';
									"
									@blur="setTimeout(() => (showDoctypeDropdown = false), 200)"
								/>
								<div
									v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0"
									class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg"
								>
									<div
										v-for="dt in filteredDoctypeOptions"
										:key="dt"
										class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900"
										@mousedown.prevent="
											newScript.reference_doctype = dt;
											doctypeSearch = dt;
											showDoctypeDropdown = false;
										"
									>
										{{ dt }}
									</div>
								</div>
							</div>
						</div>
						<div v-if="newScript.script_type === 'DocType Event'">
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>DocType Event</label
							>
							<select
								v-model="newScript.doctype_event"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
							>
								<option value="">Select event...</option>
								<option v-for="evt in doctypeEvents" :key="evt" :value="evt">
									{{ evt }}
								</option>
							</select>
						</div>
					</div>
					<div v-if="newScript.script_type === 'API'" class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>API Method</label
							>
							<input
								v-model="newScript.api_method"
								type="text"
								placeholder="e.g. my_custom_api"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
							/>
						</div>
						<div class="flex items-end">
							<label
								class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer"
							>
								<input
									v-model="newScript.allow_guest"
									type="checkbox"
									class="rounded border-gray-300"
								/>Allow Guest
							</label>
						</div>
					</div>
					<div
						v-if="newScript.script_type === 'Scheduler Event'"
						class="grid grid-cols-2 gap-4"
					>
						<div>
							<label class="block text-xs font-medium text-gray-700 mb-1"
								>Event Frequency</label
							>
							<select
								v-model="newScript.event_frequency"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
							>
								<option value="">Select frequency...</option>
								<option v-for="freq in eventFrequencies" :key="freq" :value="freq">
									{{ freq }}
								</option>
							</select>
						</div>
						<FormControl
							v-if="newScript.event_frequency === 'Cron'"
							v-model="newScript.cron_format"
							label="Cron Format"
							placeholder="*/5 * * * *"
						/>
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-700 mb-1"
							>Module (for export)</label
						>
						<div class="relative">
							<input
								v-model="moduleSearch"
								type="text"
								:placeholder="newScript.module || 'Search Module...'"
								class="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400"
								@focus="
									showModuleDropdown = true;
									showDoctypeDropdown = false;
									moduleSearch = '';
								"
								@blur="setTimeout(() => (showModuleDropdown = false), 200)"
							/>
							<div
								v-if="showModuleDropdown && filteredModuleOptions.length > 0"
								class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg"
							>
								<div
									v-for="mod in filteredModuleOptions"
									:key="mod"
									class="px-3 py-1.5 text-sm cursor-pointer hover:bg-blue-50 text-gray-900"
									@mousedown.prevent="
										newScript.module = mod;
										moduleSearch = mod;
										showModuleDropdown = false;
									"
								>
									{{ mod }}
								</div>
							</div>
						</div>
					</div>
					<div>
						<label class="block text-xs font-medium text-gray-700 mb-1"
							>Script <span class="text-red-500">*</span></label
						>
						<textarea
							v-model="newScript.script"
							class="w-full h-48 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y"
							placeholder="# Enter Python script here..."
							spellcheck="false"
						></textarea>
					</div>
				</div>

				<!-- Edit Mode -->
				<div v-else-if="scriptDialogMode === 'edit'" class="space-y-4">
					<div class="flex items-center gap-3">
						<div class="flex-1">
							<div class="text-sm font-semibold text-gray-900">
								{{ linkedScriptName }}
							</div>
							<div
								v-if="editScriptMeta.script_type"
								class="text-xs text-gray-500 mt-0.5"
							>
								{{ editScriptMeta.script_type
								}}<span v-if="editScriptMeta.reference_doctype">
									· {{ editScriptMeta.reference_doctype }}</span
								>
							</div>
						</div>
					</div>
					<div
						v-if="loadingEditScript"
						class="flex items-center justify-center py-12 text-gray-400"
					>
						<div
							class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mr-2"
						></div>
						Loading script...
					</div>
					<div v-else>
						<label class="block text-xs font-medium text-gray-700 mb-1">Script</label>
						<textarea
							v-model="editScriptContent"
							class="w-full h-72 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y"
							spellcheck="false"
						></textarea>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="showScriptEditorDialog = false">Cancel</Button>
				<Button
					v-if="scriptDialogMode === 'select'"
					variant="solid"
					:disabled="!selectedServerScript"
					@click="saveScript"
					>Link Script</Button
				>
				<Button
					v-else-if="scriptDialogMode === 'create'"
					variant="solid"
					:loading="creatingScript"
					:disabled="!newScript.name || !newScript.script_type || !newScript.script"
					@click="createAndLinkScript"
					>Create &amp; Link</Button
				>
				<Button
					v-else-if="scriptDialogMode === 'edit'"
					variant="solid"
					:loading="savingEditScript"
					:disabled="!editScriptContent || loadingEditScript"
					@click="saveEditedScript"
					>Save Changes</Button
				>
			</div>
		</template>
	</Dialog>

	<!-- Delete Script Confirmation Dialog -->
	<Dialog v-model="showDeleteScriptConfirm" :options="{ title: 'Delete Element', size: 'lg' }">
		<template #body-content>
			<div class="space-y-3 text-sm text-gray-700">
				<p>This element has a linked Server Script:</p>
				<ul class="list-disc pl-5 space-y-1">
					<li
						v-for="name in deleteScriptConfirmData.scriptNames"
						:key="name"
						class="font-medium text-gray-900"
					>
						{{ name }}
						<span
							v-if="deleteScriptConfirmData.usageMap[name] > 1"
							class="ml-2 text-xs font-normal text-amber-600"
						>
							(also used by {{ deleteScriptConfirmData.usageMap[name] - 1 }} other
							element{{ deleteScriptConfirmData.usageMap[name] > 2 ? "s" : "" }})
						</span>
					</li>
				</ul>
				<p class="text-gray-500 text-xs pt-1">
					Should the Server Script(s) be deleted as well?
				</p>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="showDeleteScriptConfirm = false">Cancel</Button>
				<Button variant="ghost" @click="confirmDeleteElement(false)"
					>Delete Element Only</Button
				>
				<Button variant="solid" theme="red" @click="confirmDeleteElement(true)"
					>Delete Element &amp; Script</Button
				>
			</div>
		</template>
	</Dialog>

	<!-- Logix Canvas (AI Script Editor): only the X hides it, and it stays mounted so reopening keeps the chat and draft -->
	<Teleport to="body">
		<div
			v-if="logixElement"
			v-show="showLogixCanvas"
			class="dialog-overlay fixed inset-0 overflow-y-auto bg-black-overlay-200 backdrop-blur-[12px]"
		>
			<div class="flex min-h-screen items-start justify-center px-4 py-4">
				<div
					class="logix-window my-8 overflow-hidden rounded-xl bg-surface-modal text-left shadow-xl"
					role="dialog"
					aria-modal="true"
					aria-label="Logix AI Assistant"
				>
					<div class="mb-6 flex items-center justify-between px-4 pt-5 sm:px-6">
						<h3 class="text-2xl font-semibold leading-6 text-ink-gray-9">
							Logix AI Assistant
						</h3>
						<Button variant="ghost" title="Close" @click="showLogixCanvas = false">
							<template #icon>
								<Icon icon="lucide:x" class="h-4 w-4 text-ink-gray-9" />
							</template>
						</Button>
					</div>
					<div class="px-4 pb-6 sm:px-6">
						<LogixCanvas
							:key="`${logixElement.id}:${logixScriptType}`"
							:element="logixElement"
							:script-type="logixScriptType"
							:current-script="logixCurrentScript"
							:event-bus="logixEventBus"
							:process-context="logixProcessContext"
							:readonly="logixReadonly"
							@close="showLogixCanvas = false"
							@script-saved="onLogixScriptSaved"
							@back="onLogixBack"
						/>
					</div>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<style scoped src="./processPageDialogs.css"></style>

<style scoped>
/* Logix AI Assistant: wider than the standard 7xl cap */
.logix-window {
	width: min(92vw, 1520px);
}
</style>
