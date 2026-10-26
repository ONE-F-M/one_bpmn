<template>
	<Dialog
		v-model="open"
		:options="{ title: 'Notification Editor', size: '5xl' }"
	>
		<template #body-content>
			<div class="space-y-3">
				<div class="flex justify-end h-4 -mt-2">
					<span
						v-if="saveStatus === 'saving'"
						class="flex items-center gap-1 text-xs text-gray-400"
					>
						<Icon
							icon="lucide:loader-2"
							class="w-3.5 h-3.5 animate-spin"
						/>
						Saving…
					</span>
					<span
						v-else-if="saveStatus === 'saved'"
						class="flex items-center gap-1 text-xs text-green-600"
					>
						<Icon
							icon="lucide:check"
							class="w-3.5 h-3.5"
						/>
						Saved to task
					</span>
					<span
						v-else
						class="text-xs text-gray-400"
					>
						All changes save automatically
					</span>
				</div>

				<Tabs
					:key="tabs.length"
					v-model="activeTab"
					:tabs="tabs"
				>
					<template #tab-item="{ tab, selected }">
						<button
							class="py-2 text-sm font-medium whitespace-nowrap border-b-2"
							:class="selected ? 'text-gray-900 border-gray-900' : 'text-gray-500 border-transparent hover:text-gray-700'"
						>
							{{ tab.label }}
						</button>
					</template>
					<template #tab-panel="{ tab }">
						<div class="pt-4">
							<NotifyContentTab
								v-if="tab.key === 'content'"
								v-model:layout="values.notifyLayout"
								v-model:subject="values.notifyAssigneeSubject"
								v-model:subject-ar="values.notifySubjectAr"
								v-model:question-en="values.notifyQuestionEn"
								v-model:question-ar="values.notifyQuestionAr"
								:html-mode="useHtml"
								:doctype="doctype"
								:task-name="taskName"
								:email-thread="thread"
							/>
							<NotifyFieldsTab
								v-if="tab.key === 'fields'"
								v-model:facts="values.notifyFacts"
								v-model:details="values.notifyDetails"
								v-model:attachments="values.notifyAttachments"
								:doctype="doctype"
								:layout="values.notifyLayout"
							/>
							<NotifyActionsTab
								v-if="tab.key === 'actions'"
								v-model:actions="actionsModel"
								v-model:hours="values.notifyTokenHours"
								v-model:conversation="values.notifyConversation"
								:task-actions="taskActions"
								:doctype="doctype"
								:layout="values.notifyLayout"
							/>
							<NotifyConversationTab
								v-if="tab.key === 'conv'"
								v-model:conversation="values.notifyConversation"
								:doctype="doctype"
							/>
							<NotifyTemplateTab
								v-if="tab.key === 'html'"
								v-model:use-html="useHtml"
								v-model:template="values.notifyAssigneeTemplate"
								v-model:body="values.notifyAssigneeBody"
								v-model:subject="values.notifyAssigneeSubject"
							/>
						</div>
					</template>
				</Tabs>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, reactive, watch, computed } from "vue";
import { Dialog, Tabs } from "frappe-ui";
import { Icon } from "@iconify/vue";
import NotifyContentTab from "@/components/NotifyContentTab.vue";
import NotifyActionsTab from "@/components/NotifyActionsTab.vue";
import NotifyFieldsTab from "@/components/NotifyFieldsTab.vue";
import NotifyConversationTab from "@/components/NotifyConversationTab.vue";
import NotifyTemplateTab from "@/components/NotifyTemplateTab.vue";
import { NOTIFY_EDITOR_ATTRS, isHtmlMode } from "@/bpmn/shared/notifyAssigneeAttrs";
import { mergeNotifyActions, serializeNotifyActions } from "@/bpmn/shared/notifyActions";
import { fieldsTabCount, parseFieldList } from "@/bpmn/shared/notifyFields";
import { useDoctypeEmailThread } from "@/composables/useDoctypeEmailThread";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	initialValues: { type: Object, default: () => ({}) },
	doctype: { type: String, default: "" },
	taskName: { type: String, default: "" },
	taskActions: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:modelValue", "save"]);

const open = computed({
	get: () => props.modelValue,
	set: (v) => {
		// Save a pending edit before the parent drops the element it writes to
		if (!v && saveTimer) saveNow();
		emit("update:modelValue", v);
	},
});

const values = reactive(Object.fromEntries(NOTIFY_EDITOR_ATTRS.map((name) => [name, ""])));
const activeTab = ref(0);
const { thread, load: loadThread } = useDoctypeEmailThread();
let lastLayout = "card";

const useHtml = computed({
	get: () => isHtmlMode(values.notifyLayout),
	set: (on) => {
		if (!on) {
			values.notifyLayout = lastLayout;
			return;
		}
		if (!isHtmlMode(values.notifyLayout)) lastLayout = values.notifyLayout;
		values.notifyLayout = "html";
	},
});

const actionsModel = computed({
	get: () => (values.notifyActions ? JSON.parse(values.notifyActions) : {}),
	set: (actions) => (values.notifyActions = serializeNotifyActions(actions)),
});

const fieldsCount = computed(() =>
	fieldsTabCount(parseFieldList(values.notifyFacts), parseFieldList(values.notifyDetails), values.notifyLayout)
);

const tabs = computed(() => [
	{ key: "content", label: "Content" },
	...(useHtml.value
		? []
		: [
				{ key: "fields", label: `Fields (${fieldsCount.value})` },
				{ key: "actions", label: `Actions (${Object.keys(actionsModel.value).length})` },
			]),
	...(values.notifyLayout === "chat" ? [{ key: "conv", label: "Conversation" }] : []),
	{ key: "html", label: "Email Template or HTML" },
]);
const lastTab = () => tabs.value.length - 1;

// The switch adds or removes the Actions tab; the Tabs key remounts the strip so its selection stays in step
watch(useHtml, () => {
	if (isReady) activeTab.value = lastTab();
});

// Auto-save state
const saveStatus = ref(""); // "" | "saving" | "saved"
let isReady = false;        // true once the dialog has finished populating
let saveTimer = null;
let savedTimer = null;

watch(
	() => props.modelValue,
	(isOpen) => {
		if (!isOpen) return;
		isReady = false;
		for (const name of NOTIFY_EDITOR_ATTRS) values[name] = props.initialValues[name] || "";
		values.notifyActions = serializeNotifyActions(mergeNotifyActions(props.taskActions, values.notifyActions));
		lastLayout = isHtmlMode(values.notifyLayout) ? "card" : values.notifyLayout;
		activeTab.value = useHtml.value ? lastTab() : 0;
		saveStatus.value = "";
		clearTimeout(saveTimer);
		clearTimeout(savedTimer);
		saveTimer = null;
		loadThread(props.doctype);
		// Allow edits to trigger auto-save only after the initial values settle
		setTimeout(() => {
			isReady = true;
		}, 0);
	}
);

watch(values, () => {
	if (!isReady) return;
	saveStatus.value = "saving";
	clearTimeout(saveTimer);
	clearTimeout(savedTimer);
	saveTimer = setTimeout(saveNow, 500);
});

function saveNow() {
	clearTimeout(saveTimer);
	saveTimer = null;
	emit("save", { ...values });
	saveStatus.value = "saved";
	savedTimer = setTimeout(() => {
		if (saveStatus.value === "saved") saveStatus.value = "";
	}, 2000);
}
</script>
