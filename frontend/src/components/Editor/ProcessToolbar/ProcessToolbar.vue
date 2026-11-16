<script setup>
import { inject, toRef } from "vue";
import { Icon } from "@iconify/vue";
import ProcessActions from "../ProcessActions/ProcessActions.vue";
import { getInitials } from "@/utils/avatar";
import { PROCESS_KEY } from "@/composables/Process/useProcessState";

const pc = inject(PROCESS_KEY);
const compact = toRef(pc.props, "compact");
const {
	activeDiagramIsActive,
	activeDiagramLabel,
	activeDiagramName,
	canEditActiveDiagram,
	diagrams,
	getStatusTheme,
	goBack,
	lockReason,
	awareness,
	processName,
	processStatus,
	selectDiagram,
	showCompactDiagramMenu,
	showStatusPopup,
} = pc;
</script>

<template>
	<header
		class="bg-white border-b px-2 py-2 flex items-center justify-between shadow-sm w-full min-h-[44px] sm:min-h-[48px]"
	>
		<div class="flex items-center gap-2 flex-1 min-w-0">
			<!-- Left: Back & Title -->
			<div
				class="flex items-center gap-2 pr-3 sm:border-r sm:border-gray-200 min-w-0 shrink"
			>
				<button
					v-if="!compact"
					class="p-1.5 hover:bg-gray-100 rounded-md transition-colors text-gray-600 shrink-0"
					title="Back to list"
					@click="goBack"
				>
					<Icon icon="lucide:chevron-left" class="w-5 h-5" />
				</button>
				<div class="flex items-center gap-2 relative min-w-0">
					<h1
						class="text-sm font-semibold text-gray-800 truncate max-w-[120px] sm:max-w-[180px] lg:max-w-[260px]"
						:title="processName"
					>
						{{ processName }}
					</h1>

					<!-- Status Icon -->
					<button
						class="p-1 rounded transition-colors"
						:class="
							canEditActiveDiagram
								? 'text-green-500 hover:bg-green-50'
								: 'text-amber-500 hover:bg-amber-50'
						"
						@click="showStatusPopup = !showStatusPopup"
					>
						<Icon
							:icon="canEditActiveDiagram ? 'lucide:pencil' : 'lucide:lock'"
							class="w-4 h-4"
						/>
					</button>

					<!-- Status Popup -->
					<div
						v-if="showStatusPopup"
						v-click-outside="() => (showStatusPopup = false)"
						class="absolute top-full left-0 mt-2 w-72 bg-white border border-gray-200 rounded-lg shadow-xl z-[60] overflow-hidden"
					>
						<div class="p-4 space-y-3">
							<div class="flex items-start gap-3">
								<div
									class="p-2 rounded-lg shrink-0"
									:class="
										canEditActiveDiagram
											? 'bg-green-50 text-green-600'
											: 'bg-amber-50 text-amber-600'
									"
								>
									<Icon
										:icon="
											canEditActiveDiagram ? 'lucide:pencil' : 'lucide:lock'
										"
										class="w-5 h-5"
									/>
								</div>
								<div class="space-y-1">
									<h3 class="text-sm font-bold text-gray-900 leading-none">
										{{
											canEditActiveDiagram
												? "Active Editing Session"
												: "Document is Locked"
										}}
									</h3>
									<p class="text-xs text-gray-500 leading-relaxed">
										{{
											canEditActiveDiagram
												? "This document is live and available for editing. Your changes are automatically saved and synchronized with the server."
												: lockReason
										}}
									</p>
								</div>
							</div>

							<div class="flex justify-end pt-2">
								<Button variant="solid" size="sm" @click="showStatusPopup = false">
									OK
								</Button>
							</div>
						</div>
					</div>

					<Badge
						v-if="processStatus"
						:theme="getStatusTheme(processStatus)"
						:label="processStatus"
						size="sm"
					/>
				</div>

				<!-- Compact mode: Diagram dropdown selector (replaces bottom tab bar) -->
				<div v-if="compact && diagrams.length > 1" class="relative ml-1 sm:ml-2">
					<button
						class="flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 py-1.5 sm:py-1 rounded-md text-xs font-medium border transition-colors active:bg-gray-200"
						:class="
							showCompactDiagramMenu
								? 'bg-gray-100 border-gray-300 text-gray-900'
								: 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'
						"
						@click="showCompactDiagramMenu = !showCompactDiagramMenu"
					>
						<span
							:class="[
								'w-1.5 h-1.5 rounded-full shrink-0',
								activeDiagramIsActive ? 'bg-green-500' : 'bg-orange-400',
							]"
						></span>
						<span class="truncate max-w-[80px] sm:max-w-[120px]">{{
							activeDiagramLabel
						}}</span>
						<Icon icon="lucide:chevron-down" class="w-3.5 h-3.5 shrink-0" />
					</button>
					<div
						v-if="showCompactDiagramMenu"
						v-click-outside="() => (showCompactDiagramMenu = false)"
						class="absolute top-full left-0 sm:left-0 mt-1 w-[calc(100vw-2rem)] sm:w-56 max-w-[280px] bg-white border border-gray-200 rounded-lg shadow-lg z-[70] py-1 max-h-64 overflow-y-auto"
					>
						<button
							v-for="tab in diagrams"
							:key="tab.name"
							class="w-full flex items-center gap-2 px-3 py-2.5 sm:py-2 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
							:class="{
								'bg-gray-50 font-semibold text-gray-900':
									activeDiagramName === tab.name,
							}"
							@click="
								selectDiagram(tab.name);
								showCompactDiagramMenu = false;
							"
						>
							<span
								:class="[
									'w-2 h-2 rounded-full shrink-0',
									tab.is_active ? 'bg-green-500' : 'bg-orange-400',
								]"
							></span>
							<span class="truncate">{{ tab.model_name }}</span>
							<Icon
								v-if="activeDiagramName === tab.name"
								icon="lucide:check"
								class="w-3.5 h-3.5 text-blue-500 ml-auto shrink-0"
							/>
						</button>
					</div>
				</div>
			</div>

			<!-- CENTER: BPMN Tools Container (Mounted natively from BpmnEditor.vue, hidden on mobile) -->
			<div
				id="bpmn-editor-toolbar"
				class="hidden sm:flex flex-1 items-center h-8 min-w-0"
			></div>

			<!-- Other Active Editors Avatars (hidden on mobile) -->
			<div
				v-if="awareness.peers.value.length > 0"
				class="hidden sm:flex items-center -space-x-2 ml-4"
			>
				<div
					v-for="user in awareness.peers.value"
					:key="user.clientId"
					:style="{ opacity: user.mode === 'idle' ? 0.5 : 1 }"
					class="relative group"
				>
					<div
						:style="{ background: user.color }"
						class="w-7 h-7 rounded-full border-2 border-white flex items-center justify-center text-[10px] font-bold text-white uppercase"
					>
						{{ getInitials(user.fullName) }}
					</div>

					<!-- Hover Tooltip -->
					<div
						class="absolute top-full left-1/2 -translate-x-1/2 mt-2 hidden group-hover:block z-[60]"
					>
						<div
							class="bg-gray-800 text-white text-[11px] py-1 px-2 rounded shadow-lg whitespace-nowrap"
						>
							{{ user.fullName }} is {{ user.mode }}
						</div>
						<div
							class="w-2 h-2 bg-gray-800 rotate-45 absolute -top-1 left-1/2 -translate-x-1/2"
						></div>
					</div>
				</div>
			</div>
		</div>

		<ProcessActions />
	</header>
</template>
