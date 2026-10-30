<template>
	<Dialog
		v-model="open"
		:options="{ title: 'Email Notification', size: '5xl' }"
		disable-outside-click-to-close
	>
		<template #body-content>
			<Tabs
				:key="tabs.length"
				v-model="activeTab"
				:tabs="tabs"
			>
				<template #tab-item="{ tab, selected }">
					<span
						class="block cursor-pointer whitespace-nowrap border-b-2 py-2 text-sm font-medium"
						:class="tabClass(tab, selected)"
					>
						{{ tab.failing ? `${tab.label} ·!` : tab.label }}
					</span>
				</template>
				<template #tab-panel="{ tab }">
					<div class="space-y-4 px-1 pt-4">
						<template v-if="tab.key === 'sending'">
							<Autocomplete
								:compare-fn="compareOption"
								label="Email Account · required"
								placeholder="Select an account"
								:options="toOptions(options.accounts.value)"
								:loading="options.loading.value"
								:model-value="values.emailAccount || null"
								@update:model-value="(option) => (values.emailAccount = option?.value || '')"
							/>
							<ErrorMessage
								v-if="errors.emailAccount"
								:message="errors.emailAccount"
							/>
							<FormControl
								type="checkbox"
								label="Based on a Specific Doctype Record"
								:model-value="useDoctype"
								@update:model-value="setUseDoctype"
							/>
							<p class="text-p-sm text-ink-gray-5">
								Uses the process's document for placeholders, Document Field recipients, key facts and the live
								status.
							</p>
							<Autocomplete
								v-if="useDoctype"
								:compare-fn="compareOption"
								label="DocType"
								:options="toOptions(options.doctypes.value)"
								:model-value="values.emailDoctype || null"
								@update:model-value="setDoctype"
							/>
						</template>

						<EmailRecipientsTab
							v-if="tab.key === 'recipients'"
							:values="values"
							:doctype="useDoctype ? values.emailDoctype : ''"
							:options="options"
							:error="errors.recipients"
							@update="(name, value) => (values[name] = value)"
						/>

						<EmailNoticeContentTab
							v-if="tab.key === 'content'"
							:values="values"
							:doctype="values.emailDoctype"
							:use-html="useHtml"
							:use-doctype="useDoctype"
							:process-model="processModel"
							:subject-error="errors.emailSubject"
							@update="(name, value) => (values[name] = value)"
						/>

						<NotifyFieldsTab
							v-if="tab.key === 'fields'"
							v-model:facts="values.emailFacts"
							v-model:details="values.emailDetails"
							v-model:attachments="values.emailAttachments"
							:doctype="values.emailDoctype"
							link-life="expire after 30 days"
						/>

						<template v-if="tab.key === 'html'">
							<FormControl
								type="checkbox"
								label="Use custom HTML"
								:model-value="useHtml"
								@update:model-value="(on) => (useHtml = on)"
							/>
							<p class="text-p-sm text-ink-gray-5">
								For existing tasks. The email is built and sent exactly as today: the Email Body in the standard frame with
								Open in ERPNext, cleaned for AMP. Tasks that already have an Email Body open with this on.
							</p>
							<FormControl
								v-if="useHtml"
								v-model="values.emailBody"
								type="textarea"
								label="Email Body"
								:rows="14"
								class="[&_textarea]:font-mono"
								spellcheck="false"
							>
								<template #description>
									<p
										v-pre
										class="text-p-sm text-ink-gray-5"
									>
										Supports Jinja2: {{ doc.field_name }}, {{ instance.name }}, etc.
									</p>
								</template>
							</FormControl>
						</template>
					</div>
				</template>
			</Tabs>
		</template>
		<template #actions>
			<div class="flex flex-wrap items-center justify-end gap-2">
				<p
					class="mr-auto text-p-sm"
					:class="tried && failingTabs.length ? 'text-ink-red-4' : 'text-ink-gray-5'"
				>
					{{ footerHint }}
				</p>
				<Button
					label="Cancel"
					@click="open = false"
				/>
				<Button
					variant="solid"
					label="Save"
					@click="save"
				/>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { Autocomplete, Button, Dialog, ErrorMessage, FormControl, Tabs } from "frappe-ui";
import EmailNoticeContentTab from "@/components/EmailNoticeContentTab.vue";
import EmailRecipientsTab from "@/components/EmailRecipientsTab.vue";
import NotifyFieldsTab from "@/components/NotifyFieldsTab.vue";
import { EMAIL_EDITOR_ATTRS, changedAttrs, emailLayout, validateEmailNotification } from "@/bpmn/shared/emailNotification";
import { useEmailNotificationOptions } from "@/composables/useEmailNotificationOptions";
import { compareOption } from "@/utils/compareOption";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	// the task's saved email attributes, emailBody decoded
	initialValues: { type: Object, default: () => ({}) },
	// the process model, so the translate endpoint can check write on it
	processModel: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "save"]);

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
});

const TABS = [
	{ key: "sending", label: "Sending" },
	{ key: "recipients", label: "Recipients" },
	{ key: "content", label: "Content" },
	{ key: "fields", label: "Fields" },
	{ key: "html", label: "Custom HTML" },
];

const options = useEmailNotificationOptions();
// the working copy; nothing reaches the task until Save
const values = reactive(Object.fromEntries(EMAIL_EDITOR_ATTRS.map((name) => [name, ""])));
// the selected tab by key, since the Fields tab comes and goes and shifts the indexes
const activeKey = ref("sending");
const tried = ref(false);

watch(open, (isOpen) => {
	if (!isOpen) return;
	for (const name of EMAIL_EDITOR_ATTRS) values[name] = props.initialValues[name] || "";
	values.emailLayout = emailLayout(values);
	tried.value = false;
	activeKey.value = useHtml.value && values.emailBody ? "html" : "sending";
	options.loadLists();
});

const validation = computed(() => validateEmailNotification(values));
const failingTabs = computed(() => (tried.value ? validation.value.tabs : []));
const errors = computed(() => (tried.value ? validation.value.errors : {}));
// Fields only when the email is based on a record and sends the Notice
const activeTab = computed({
	get: () => Math.max(0, tabs.value.findIndex((t) => t.key === activeKey.value)),
	set: (index) => (activeKey.value = tabs.value[index]?.key || "sending"),
});

const tabs = computed(() =>
	TABS.filter((t) => t.key !== "fields" || (useDoctype.value && !useHtml.value)).map((t) => ({
		...t,
		failing: failingTabs.value.includes(t.key),
	}))
);
const changed = computed(() => changedAttrs(props.initialValues, values));
const useDoctype = computed(() => values.emailUseDoctype === "true");
const useHtml = computed({
	get: () => values.emailLayout === "html",
	set: (on) => (values.emailLayout = on ? "html" : "notice"),
});

const footerHint = computed(() => {
	if (tried.value && failingTabs.value.length) return "Fix the marked fields before saving.";
	return changed.value.length ? "Save writes these values to the task; Cancel discards them." : "Nothing to save yet.";
});

function tabClass(tab, selected) {
	if (tab.failing) return selected ? "border-ink-red-4 text-ink-red-4" : "border-transparent text-ink-red-4";
	return selected ? "border-ink-gray-9 text-ink-gray-9" : "border-transparent text-ink-gray-5 hover:text-ink-gray-7";
}

const toOptions = (names) => names.map((name) => ({ label: name, value: name }));

// off clears the DocType, as the panel did
function setUseDoctype(on) {
	values.emailUseDoctype = on ? "true" : "";
	if (!on) values.emailDoctype = "";
}

// fields picked from one DocType do not exist on another
function setDoctype(option) {
	const doctype = option?.value || "";
	if (values.emailDoctype && doctype !== values.emailDoctype) {
		values.emailToDocFields = "";
		values.emailToTableField = "";
		values.emailToTableUserField = "";
	}
	values.emailDoctype = doctype;
}

function save() {
	tried.value = true;
	const [firstFailing] = validation.value.tabs;
	if (firstFailing) {
		activeKey.value = firstFailing;
		return;
	}
	emit("save", { values: { ...values }, changed: changed.value });
}
</script>
