<template>
	<Dialog
		v-model="open"
		:options="{ title: 'Email Notification', size: '5xl' }"
		disable-outside-click-to-close
	>
		<template #body-content>
			<Tabs
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

						<template v-if="tab.key === 'content'">
							<FormControl
								v-model="values.emailSubject"
								type="text"
								label="Subject · required"
								placeholder="e.g. Action Required: {{ doc.name }}"
							>
								<template #description>
									<ErrorMessage
										v-if="errors.emailSubject"
										:message="errors.emailSubject"
									/>
									<p
										v-else
										v-pre
										class="text-p-sm text-ink-gray-5"
									>
										Supports Jinja2: use {{ doc.field_name }} for document values.
									</p>
								</template>
							</FormControl>
						</template>

						<template v-if="tab.key === 'html'">
							<FormControl
								type="checkbox"
								label="Use custom HTML"
								:model-value="true"
								disabled
							/>
							<p class="text-p-sm text-ink-gray-5">
								The email is built and sent exactly as today: the Email Body in the standard frame with Open in
								ERPNext, cleaned for AMP. It stays on until the Notice layout is added.
							</p>
							<FormControl
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
import EmailRecipientsTab from "@/components/EmailRecipientsTab.vue";
import { EMAIL_EDITOR_ATTRS, changedAttrs, validateEmailNotification } from "@/bpmn/shared/emailNotification";
import { useEmailNotificationOptions } from "@/composables/useEmailNotificationOptions";
import { compareOption } from "@/utils/compareOption";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	// the task's saved email attributes, emailBody decoded
	initialValues: { type: Object, default: () => ({}) },
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
	{ key: "html", label: "Custom HTML" },
];

const options = useEmailNotificationOptions();
// the working copy; nothing reaches the task until Save
const values = reactive(Object.fromEntries(EMAIL_EDITOR_ATTRS.map((name) => [name, ""])));
const activeTab = ref(0);
const tried = ref(false);

watch(open, (isOpen) => {
	if (!isOpen) return;
	for (const name of EMAIL_EDITOR_ATTRS) values[name] = props.initialValues[name] || "";
	tried.value = false;
	activeTab.value = values.emailBody ? TABS.length - 1 : 0;
	options.loadLists();
});

const validation = computed(() => validateEmailNotification(values));
const failingTabs = computed(() => (tried.value ? validation.value.tabs : []));
const errors = computed(() => (tried.value ? validation.value.errors : {}));
const tabs = computed(() => TABS.map((t) => ({ ...t, failing: failingTabs.value.includes(t.key) })));
const changed = computed(() => changedAttrs(props.initialValues, values));
const useDoctype = computed(() => values.emailUseDoctype === "true");

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
		activeTab.value = TABS.findIndex((t) => t.key === firstFailing);
		return;
	}
	emit("save", { values: { ...values }, changed: changed.value });
}
</script>
