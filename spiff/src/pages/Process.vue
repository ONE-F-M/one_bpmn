<template>
	<div class="h-full flex flex-col min-w-0 overflow-hidden">
		<ProcessToolbar />

		<!-- Notification Banner (Background) -->
		<div v-if="notification.show && !isAnyDialogOpen" class="px-4 py-2">
			<div
				class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm shadow-sm border"
				:class="{
					'bg-green-50 border-green-200 text-green-800': notification.theme === 'green',
					'bg-red-50 border-red-200 text-red-800': notification.theme === 'red',
					'bg-yellow-50 border-yellow-200 text-yellow-800':
						notification.theme === 'yellow',
					'bg-blue-50 border-blue-200 text-blue-800':
						!notification.theme || notification.theme === 'blue',
				}"
			>
				<!-- Icon -->
				<Icon
					:icon="
						notification.theme === 'green'
							? 'lucide:check-circle-2'
							: notification.theme === 'red'
								? 'lucide:alert-circle'
								: 'lucide:info'
					"
					class="w-5 h-5 mt-0.5 flex-shrink-0"
				/>
				<!-- Content -->
				<div class="flex-1 min-w-0">
					<p class="font-semibold">{{ notification.title }}</p>
					<p v-if="notification.message" class="mt-0.5 whitespace-pre-line break-words">
						{{ notification.message }}
					</p>
				</div>
				<!-- Close button -->
				<button
					class="flex-shrink-0 p-0.5 rounded hover:bg-black/10 transition-colors"
					aria-label="Dismiss notification"
					@click="notification.show = false"
				>
					<Icon icon="lucide:x" class="w-4 h-4" />
				</button>
			</div>
		</div>

		<ProcessDiagramTab />
		<ProcessLogixTab />
		<ProcessDmnTab />
		<ProcessLauncherDialogs />

		<Dialog
			v-model="showUnsavedNavigationWarning"
			:options="{ title: 'Unsaved Changes', size: 'sm' }"
		>
			<template #body-content>
				<div class="text-base text-gray-700">
					You have unsaved changes. Are you sure you want to leave? Your pending edits
					will be lost.
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2 justify-end w-full">
					<Button variant="subtle" @click="cancelNavigation">No, stay here</Button>
					<Button variant="solid" theme="red" @click="confirmNavigation"
						>Yes, leave</Button
					>
				</div>
			</template>
		</Dialog>

		<ProcessDeployTab />
		<ProcessConfigurationTab />
	</div>
</template>

<script setup>
import { provide } from "vue";
import { Icon } from "@iconify/vue";
import ProcessToolbar from "@/components/Editor/ProcessToolbar/ProcessToolbar.vue";
import ProcessDiagramTab from "@/components/Editor/ProcessDiagramTab/ProcessDiagramTab.vue";
import ProcessLogixTab from "@/components/Editor/ProcessLogixTab/ProcessLogixTab.vue";
import ProcessDmnTab from "@/components/Editor/ProcessDmnTab/ProcessDmnTab.vue";
import ProcessLauncherDialogs from "@/components/Editor/ProcessLauncherDialogs/ProcessLauncherDialogs.vue";
import ProcessDeployTab from "@/components/Editor/ProcessDeployTab/ProcessDeployTab.vue";
import ProcessConfigurationTab from "@/components/Editor/ProcessConfigurationTab/ProcessConfigurationTab.vue";
import { createProcessContext, PROCESS_KEY } from "@/composables/Process/useProcessState";
import { useProcessReassign } from "@/composables/Process/useProcessReassign";
import { useProcessDmn } from "@/composables/Process/useProcessDmn";
import { useProcessSave } from "@/composables/Process/useProcessSave";
import { useProcessDocument } from "@/composables/Process/useProcessDocument";
import { useProcessScripts } from "@/composables/Process/useProcessScripts";
import { useProcessLaunchers } from "@/composables/Process/useProcessLaunchers";
import { useProcessZoom } from "@/composables/Process/useProcessZoom";
import { useProcessDeploy } from "@/composables/Process/useProcessDeploy";
import { useProcessConfig } from "@/composables/Process/useProcessConfig";
import { useProcessTabs } from "@/composables/Process/useProcessTabs";
import { useProductionReview } from "@/composables/useProductionReview";

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

const pc = createProcessContext(props);
provide(PROCESS_KEY, pc);
useProcessReassign(pc);
useProcessDmn(pc);
useProcessSave(pc);
useProcessDocument(pc);
useProcessScripts(pc);
useProcessLaunchers(pc);
useProcessZoom(pc);
useProcessDeploy(pc);
useProcessConfig(pc);
useProcessTabs(pc);
useProductionReview(pc);

const {
	cancelNavigation,
	confirmNavigation,
	isAnyDialogOpen,
	notification,
	showUnsavedNavigationWarning,
} = pc;
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

.scrollbar-hide::-webkit-scrollbar {
	display: none;
}
.scrollbar-hide {
	-ms-overflow-style: none;
	scrollbar-width: none;
}
</style>
