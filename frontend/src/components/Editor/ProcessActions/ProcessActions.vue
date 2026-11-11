<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import { PROCESS_KEY } from "@/composables/Process/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	activeDiagramName,
	activeVersionName,
	deployModel,
	deploying,
	disableModel,
	disabling,
	editorRef,
	exportCurrentDiagram,
	isActiveModel,
	isBaInstance,
	isExecutable,
	isMobile,
	isProductionInstance,
	lastEditTooltip,
	openReview,
	reassignMode,
	showActionsMenu,
	showFileMenu,
	showMobileMoreMenu,
	toggleComments,
	toggleReassignMode,
	toggleVersionHistory,
	totalCommentCount,
	triggerImport,
	triggerImportConfig,
} = pc;
</script>

<template>
	<div class="flex items-center gap-2 shrink-0 border-l border-gray-200 pl-3 ml-2">
		<!-- Desktop: Individual action buttons -->
		<template v-if="!isMobile">
			<!-- Version History Button -->
			<button
				class="w-8 h-8 flex items-center justify-center rounded transition-colors"
				:class="[
					'hover:bg-gray-100 text-gray-600',
					{ 'opacity-40 cursor-not-allowed': !activeDiagramName },
				]"
				:title="lastEditTooltip"
				:disabled="!activeDiagramName"
				@click="toggleVersionHistory"
			>
				<Icon icon="lucide:history" class="w-4 h-4" />
			</button>

			<!-- Comments Sidebar Toggle -->
			<button
				class="w-8 h-8 flex items-center justify-center rounded transition-colors relative"
				:class="[
					editorRef?.showTimeline
						? 'bg-blue-100 text-blue-700'
						: 'hover:bg-gray-100 text-gray-600',
					{ 'opacity-40 cursor-not-allowed': !activeDiagramName },
				]"
				title="Toggle Comments Panel"
				:disabled="!activeDiagramName"
				@click="toggleComments"
			>
				<Icon icon="lucide:message-square" class="w-4 h-4" />
				<span
					v-if="totalCommentCount > 0"
					class="absolute top-1 right-1 w-3 h-3 bg-blue-600 text-white text-[8px] font-bold rounded-full flex items-center justify-center border border-white"
				>
					{{ totalCommentCount }}
				</span>
			</button>

			<!-- File menu dropdown (Import / Export) -->
			<div class="relative">
				<button
					class="w-8 h-8 flex items-center justify-center hover:bg-gray-100 rounded transition-colors text-gray-600"
					title="Import / Export"
					@click="showFileMenu = !showFileMenu"
				>
					<Icon icon="lucide:arrow-down-up" class="w-4 h-4" />
				</button>
				<div
					v-if="showFileMenu"
					v-click-outside="() => (showFileMenu = false)"
					class="absolute right-0 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg z-[70] py-1"
				>
					<button
						class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						@click="
							triggerImport();
							showFileMenu = false;
						"
					>
						<Icon icon="lucide:download" class="w-4 h-4" />
						Import BPMN
					</button>
					<button
						class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						@click="
							triggerImportConfig();
							showFileMenu = false;
						"
					>
						<Icon icon="lucide:file-json" class="w-4 h-4" />
						Import Config
					</button>
					<div class="border-t border-gray-100 my-1"></div>
					<button
						class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						:disabled="!activeDiagramName"
						:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						@click="
							exportCurrentDiagram();
							showFileMenu = false;
						"
					>
						<Icon icon="lucide:upload" class="w-4 h-4" />
						Export
					</button>
				</div>
			</div>

			<!-- Actions menu (last - primary actions) -->
			<div class="relative">
				<button
					class="h-7 flex items-center gap-1 px-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors text-xs font-medium leading-none"
					title="Actions"
					:disabled="!activeDiagramName"
					:class="{ 'opacity-50 cursor-not-allowed': !activeDiagramName }"
					@click="showActionsMenu = !showActionsMenu"
				>
					<Icon icon="lucide:zap" class="w-3.5 h-3.5" />
					Actions
					<Icon icon="lucide:chevron-down" class="w-3 h-3" />
				</button>
				<div
					v-if="showActionsMenu"
					v-click-outside="() => (showActionsMenu = false)"
					class="absolute right-0 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-[70] py-1"
				>
					<!-- Deploy (only when the model is not yet Active) -->
					<button
						v-if="!isActiveModel"
						class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						:disabled="!activeDiagramName || deploying || !!activeVersionName"
						:class="{
							'opacity-40 cursor-not-allowed':
								!activeDiagramName || deploying || !!activeVersionName,
						}"
						@click="
							deployModel();
							showActionsMenu = false;
						"
					>
						<Icon
							:icon="deploying ? 'lucide:loader-2' : 'lucide:rocket'"
							class="w-4 h-4"
							:class="{ 'animate-spin': deploying }"
						/>
						{{ deploying ? "Deploying…" : "Deploy" }}
					</button>
					<!-- Disable (only when the model is Active) -->
					<button
						v-if="isActiveModel"
						class="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
						:disabled="!activeDiagramName || disabling"
						:class="{
							'opacity-40 cursor-not-allowed': !activeDiagramName || disabling,
						}"
						@click="
							disableModel();
							showActionsMenu = false;
						"
					>
						<Icon
							:icon="disabling ? 'lucide:loader-2' : 'lucide:power-off'"
							class="w-4 h-4"
							:class="{ 'animate-spin': disabling }"
						/>
						{{ disabling ? "Disabling…" : "Disable" }}
					</button>
					<!-- Production review (only on a BA instance) -->
					<template v-if="isExecutable && isBaInstance">
						<div class="border-t border-gray-100 my-1"></div>
						<button
							class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							:disabled="!activeDiagramName"
							:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
							@click="
								openReview('doctypes');
								showActionsMenu = false;
							"
						>
							<Icon icon="lucide:table-2" class="w-4 h-4" />
							Review Doctypes
						</button>
						<button
							class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
							:disabled="!activeDiagramName"
							:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
							@click="
								openReview('workflow');
								showActionsMenu = false;
							"
						>
							<Icon icon="lucide:workflow" class="w-4 h-4" />
							Review Workflow Objects
						</button>
					</template>
					<!-- Release Property Panel (only on a Production instance) -->
					<template v-if="isProductionInstance">
						<div v-if="isExecutable" class="border-t border-gray-100 my-1"></div>
						<button
							class="w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors"
							:disabled="!activeDiagramName"
							:class="[
								reassignMode
									? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
									: 'text-gray-700 hover:bg-gray-50',
								{ 'opacity-40 cursor-not-allowed': !activeDiagramName },
							]"
							@click="
								toggleReassignMode();
								showActionsMenu = false;
							"
						>
							<Icon
								:icon="reassignMode ? 'lucide:lock' : 'lucide:lock-open'"
								class="w-4 h-4"
							/>
							{{ reassignMode ? "Lock Property Panel" : "Release Property Panel" }}
						</button>
					</template>
				</div>
			</div>
		</template>

		<!-- Mobile: "More" overflow dropdown -->
		<div v-if="isMobile" class="relative">
			<button
				class="w-8 h-8 flex items-center justify-center hover:bg-gray-100 rounded transition-colors text-gray-600"
				title="More actions"
				@click="showMobileMoreMenu = !showMobileMoreMenu"
			>
				<Icon icon="lucide:more-vertical" class="w-4 h-4" />
			</button>
			<div
				v-if="showMobileMoreMenu"
				v-click-outside="() => (showMobileMoreMenu = false)"
				class="absolute right-0 mt-1 w-44 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1"
			>
				<button
					v-if="isActiveModel"
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
					:disabled="!activeDiagramName || disabling"
					:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName || disabling }"
					@click="
						disableModel();
						showMobileMoreMenu = false;
					"
				>
					<Icon
						:icon="disabling ? 'lucide:loader-2' : 'lucide:power-off'"
						class="w-4 h-4"
					/>
					{{ disabling ? "Disabling…" : "Disable" }}
				</button>
				<button
					v-else
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					:disabled="!activeDiagramName || deploying || !!activeVersionName"
					:class="{
						'opacity-40 cursor-not-allowed':
							!activeDiagramName || deploying || !!activeVersionName,
					}"
					@click="
						deployModel();
						showMobileMoreMenu = false;
					"
				>
					<Icon
						:icon="deploying ? 'lucide:loader-2' : 'lucide:rocket'"
						class="w-4 h-4"
					/>
					{{ deploying ? "Deploying…" : "Deploy" }}
				</button>
				<template v-if="isExecutable && isBaInstance">
					<button
						class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						:disabled="!activeDiagramName"
						:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						@click="
							openReview('doctypes');
							showMobileMoreMenu = false;
						"
					>
						<Icon icon="lucide:table-2" class="w-4 h-4" />
						Review Doctypes
					</button>
					<button
						class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
						:disabled="!activeDiagramName"
						:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
						@click="
							openReview('workflow');
							showMobileMoreMenu = false;
						"
					>
						<Icon icon="lucide:workflow" class="w-4 h-4" />
						Review Workflow Objects
					</button>
				</template>
				<template v-if="isProductionInstance">
					<button
						class="w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors"
						:disabled="!activeDiagramName"
						:class="[
							reassignMode
								? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
								: 'text-gray-700 hover:bg-gray-50',
							{ 'opacity-40 cursor-not-allowed': !activeDiagramName },
						]"
						@click="
							toggleReassignMode();
							showMobileMoreMenu = false;
						"
					>
						<Icon
							:icon="reassignMode ? 'lucide:lock' : 'lucide:lock-open'"
							class="w-4 h-4"
						/>
						{{ reassignMode ? "Lock Property Panel" : "Release Property Panel" }}
					</button>
				</template>
				<button
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					:disabled="!activeDiagramName"
					:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
					@click="
						toggleVersionHistory();
						showMobileMoreMenu = false;
					"
				>
					<Icon icon="lucide:history" class="w-4 h-4" />
					Version history
				</button>
				<div class="border-t border-gray-100 my-1"></div>
				<button
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					@click="
						triggerImport();
						showMobileMoreMenu = false;
					"
				>
					<Icon icon="lucide:download" class="w-4 h-4" />
					Import BPMN
				</button>
				<button
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					@click="
						triggerImportConfig();
						showMobileMoreMenu = false;
					"
				>
					<Icon icon="lucide:file-json" class="w-4 h-4" />
					Import Config
				</button>
				<button
					class="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					:disabled="!activeDiagramName"
					:class="{ 'opacity-40 cursor-not-allowed': !activeDiagramName }"
					@click="
						exportCurrentDiagram();
						showMobileMoreMenu = false;
					"
				>
					<Icon icon="lucide:upload" class="w-4 h-4" />
					Export
				</button>
			</div>
		</div>
	</div>
</template>
