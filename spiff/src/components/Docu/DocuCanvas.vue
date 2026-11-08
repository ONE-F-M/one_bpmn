<template>
	<Teleport to="body">
		<div v-show="open" class="dc-overlay">
			<div class="dc-window">
				<div class="dc-window-header">
					<div class="dc-window-title">
						<span class="dc-badge">Docu</span>
						<span class="dc-subtitle">DocType Builder</span>
						<span v-if="dtName" class="dc-dt-chip" :title="dtName">{{ dtName }}</span>
					</div>
					<button class="dc-icon-btn" title="Close" @click="emit('close')">
						<Icon icon="lucide:x" class="w-4 h-4" />
					</button>
				</div>
				<div class="dc-root">
					<div class="dc-chat-panel">
						<AgentChatPanel
							agent-id="docu_agent"
							variant="docked"
							layout="conversation"
							:apply-targets="['apply-schema', 'apply-script']"
							:context="docuTurnContext"
							:host-context-line="hostContextLine"
							:cards="cardRegistry"
							@card-action="onDocuCardAction"
						/>
					</div>
					<div class="dc-builder-panel" :inert="!canChange">
						<div class="dc-view-tabs">
							<button
								class="dc-view-tab"
								:class="{ active: view === 'form' }"
								@click="view = 'form'"
							>
								Form
							</button>
							<button
								class="dc-view-tab"
								:class="{ active: view === 'settings' }"
								@click="view = 'settings'"
							>
								Settings
							</button>
						</div>
						<template v-if="view === 'form'">
							<div class="dc-builder-topbar">
								<div class="dc-form-name">
									<input
										v-model="dtName"
										class="dc-name-input"
										placeholder="DocType name (e.g. Vehicle Inspection)"
										@focus="selectForm()"
									/>
								</div>
							</div>
							<DocuFormCanvas />
						</template>
						<DocuSettingsView v-else />
					</div>
					<DocuPropertiesPanel />
				</div>
				<DocuChangesPreview />
				<DocuApplyBar />
			</div>
		</div>
	</Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, provide, watch } from "vue";
import { Icon } from "@iconify/vue";
import AgentChatPanel from "@/components/Chat/AgentChatPanel.vue";
import DocuApplyBar from "@/components/Docu/DocuApplyBar.vue";
import DocuChangesPreview from "@/components/Docu/DocuChangesPreview.vue";
import DocuFormCanvas from "@/components/Docu/DocuFormCanvas.vue";
import DocuPropertiesPanel from "@/components/Docu/DocuPropertiesPanel.vue";
import DocuSettingsView from "@/components/Docu/DocuSettingsView.vue";
import { DOCU_KEY } from "@/composables/useDocu";
import { useDocuAutosave } from "@/composables/useDocuAutosave";
import { useDocuChat } from "@/composables/useDocuChat";
import { useDocuHistory } from "@/composables/useDocuHistory";
import { useDocuIr } from "@/composables/useDocuIr";
import { useDocuSettings } from "@/composables/useDocuSettings";
import { useDocuTree } from "@/composables/useDocuTree";
import { cardRegistry } from "@/utils/cardRegistry";

const props = defineProps({
	element: { type: Object, default: null },
	doctype: { type: String, default: "" },
	attr: { type: String, default: "" },
	processContext: { type: Object, default: null },
	open: { type: Boolean, default: true },
});
const emit = defineEmits(["close", "applied"]);

const settings = useDocuSettings({ doctype: props.doctype, onChange });
const tree = useDocuTree();
const ir = useDocuIr({ tree, settings });
const history = useDocuHistory({ currentIr: ir.currentIr, loadIr: ir.loadIr });
const autosave = useDocuAutosave({
	dtName: settings.dtName,
	contentCount: tree.contentCount,
	currentIr: ir.currentIr,
	appliedName: ir.appliedName,
	loadIr: ir.loadIr,
	isRestoring: history.isRestoring,
	getProcessContext: () => props.processContext,
	emit,
});
const chat = useDocuChat({
	props,
	dtName: settings.dtName,
	dtModule: settings.dtModule,
	loadIr: ir.loadIr,
	autosave,
});

provide(DOCU_KEY, { ...settings, ...tree, ...ir, ...autosave, ...chat });

const { dtName, dtModule, dtAutoname, isChild, dtSettings, loadRoles, loadModules } = settings;
const { view, tabs, selectForm, buildTree } = tree;
const { canChange } = autosave;
const { docuTurnContext, hostContextLine, onDocuCardAction } = chat;

function onChange() {
	history.scheduleSnapshot();
	autosave.scheduleAutosave();
}

function stopPolling() {
	history.stopTimers();
	autosave.stopTimers();
	window.removeEventListener("keydown", history.onGlobalKeydown, true);
}

// Undo/redo shortcuts belong to the diagram while the canvas is hidden.
watch(
	() => props.open,
	(open) => {
		if (open) window.addEventListener("keydown", history.onGlobalKeydown, true);
		else window.removeEventListener("keydown", history.onGlobalKeydown, true);
	},
);

onBeforeUnmount(() => {
	stopPolling();
	document.body.classList.remove("docu-open");
});

onMounted(async () => {
	document.body.classList.add("docu-open");
	buildTree([]); // start with an empty tab/section/column so the canvas is usable
	selectForm();
	loadModules(); // populate the module picker (fire-and-forget)
	loadRoles(); // populate the permission-rule role picker
	await autosave.loadCanChange();
	if (props.doctype) {
		// A doctype is already selected on the shape: load its form builder view.
		await ir.loadSchema(props.doctype);
		const stored = autosave.readUnsaved();
		if (stored && stored !== JSON.stringify(ir.currentIr()))
			autosave.unsavedDesign.value = stored;
	}

	// Undo/redo: seed the baseline snapshot, then record on every edit.
	nextTick(() => {
		history.recordSnapshot();
		watch(
			[tabs, dtName, dtModule, dtAutoname, isChild, dtSettings],
			() => {
				history.scheduleSnapshot();
				autosave.scheduleAutosave();
			},
			{ deep: true },
		);
	});
	window.addEventListener("keydown", history.onGlobalKeydown, true);
});
</script>

<style scoped src="@/components/Docu/docuCanvas.css"></style>

<style>
body.docu-open #headlessui-portal-root {
	position: relative;
	z-index: 2100;
}
</style>
