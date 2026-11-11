<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import LogixCanvas from "@/components/Logix/LogixCanvas/LogixCanvas.vue";
import ProcessScriptModal from "@/components/Modals/ProcessScriptModal/ProcessScriptModal.vue";
import { PROCESS_KEY } from "@/composables/Process/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	confirmDeleteElement,
	deleteScriptConfirmData,
	logixCurrentScript,
	logixElement,
	logixEventBus,
	logixProcessContext,
	logixReadonly,
	logixScriptType,
	onLogixBack,
	onLogixScriptSaved,
	showDeleteScriptConfirm,
	showLogixCanvas,
} = pc;
</script>

<template>
	<ProcessScriptModal />

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

<style scoped src="./ProcessLogixTab.css"></style>
