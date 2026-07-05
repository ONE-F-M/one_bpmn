<template>
	<Dialog v-model="open" :options="{ title: 'Notification Editor', size: '4xl' }">
		<template #body-content>
			<div class="space-y-4">
				<!-- Auto-save status indicator -->
				<div class="flex justify-end h-4 -mt-2">
					<span
						v-if="saveStatus === 'saving'"
						class="flex items-center gap-1 text-xs text-gray-400"
					>
						<Icon icon="lucide:loader-2" class="w-3.5 h-3.5 animate-spin" />
						Saving…
					</span>
					<span
						v-else-if="saveStatus === 'saved'"
						class="flex items-center gap-1 text-xs text-green-600"
					>
						<Icon icon="lucide:check" class="w-3.5 h-3.5" />
						Saved
					</span>
				</div>

				<!-- Subject -->
				<div>
					<label class="block text-xs font-medium text-gray-700 mb-1">
						Subject
					</label>
					<input
						v-model="subject"
						type="text"
						placeholder="Email subject..."
						class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
					/>
					<p class="text-xs text-gray-400 mt-1" v-pre>
						Jinja template variables are supported: <code class="bg-gray-100 px-1 rounded">{{ doc.name }}</code>, etc.
					</p>
				</div>

				<!-- Email Template Pre-populate -->
				<div>
					<label class="block text-xs font-medium text-gray-700 mb-1">
						Pre-populate from Email Template
					</label>
					<div class="relative">
						<Icon icon="lucide:search" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
						<input
							v-model="templateSearch"
							type="text"
							placeholder="Search email templates..."
							class="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
							@focus="showTemplateDropdown = true"
							@blur="onBlurTemplate"
						/>
						<div
							v-if="showTemplateDropdown && filteredTemplates.length > 0"
							class="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white border border-gray-200 rounded-md shadow-lg"
						>
							<div
								v-for="tpl in filteredTemplates"
								:key="tpl.name"
								@mousedown.prevent="selectTemplate(tpl)"
								class="px-3 py-2 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 border-b border-gray-50 last:border-b-0"
							>
								<div class="font-medium">{{ tpl.name }}</div>
								<div v-if="tpl.subject" class="text-xs text-gray-500 mt-0.5">{{ tpl.subject }}</div>
							</div>
						</div>
						<div
							v-if="showTemplateDropdown && !loadingTemplates && filteredTemplates.length === 0 && templateSearch"
							class="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg"
						>
							<div class="px-3 py-3 text-sm text-gray-400 text-center">No templates found</div>
						</div>
					</div>
					<!-- Template-attached sign -->
					<div class="mt-2">
						<span
							v-if="attachedTemplate"
							class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-50 text-green-700 text-xs font-medium border border-green-200"
						>
							<Icon icon="lucide:paperclip" class="w-3.5 h-3.5" />
							Template attached: {{ attachedTemplate }}
							<button
								type="button"
								class="ml-1 text-green-600 hover:text-green-900"
								title="Detach template"
								@click="detachTemplate"
							>
								<Icon icon="lucide:x" class="w-3.5 h-3.5" />
							</button>
						</span>
						<span
							v-else
							class="inline-flex items-center gap-1.5 text-xs text-gray-400"
						>
							<Icon icon="lucide:paperclip-off" class="w-3.5 h-3.5" />
							No template attached
						</span>
					</div>
					<p class="text-xs text-gray-400 mt-1">
						Selecting a template copies its HTML into the editor below. Changes here do not affect the original template.
					</p>
				</div>

				<!-- HTML Editor -->
				<div>
					<label class="block text-xs font-medium text-gray-700 mb-1">
						Notification HTML Body
					</label>
					<textarea
						v-model="htmlBody"
						class="w-full h-64 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y"
						placeholder="Enter notification HTML here..."
						spellcheck="false"
					></textarea>
					<p class="text-xs text-gray-400 mt-1" v-pre>
						Jinja template variables are supported: <code class="bg-gray-100 px-1 rounded">{{ doc.name }}</code>,
						<code class="bg-gray-100 px-1 rounded">{{ doc.owner }}</code>, etc.
					</p>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, watch, computed } from "vue";
import { frappeRequest } from "frappe-ui";
import { frappeGet } from "@/bpmn/shared/frappeResource";
import { Icon } from "@iconify/vue";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	initialBody: { type: String, default: "" },
	initialSubject: { type: String, default: "" },
	initialTemplate: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "save"]);

const open = computed({
	get: () => props.modelValue,
	set: (v) => emit("update:modelValue", v),
});

const htmlBody = ref("");
const subject = ref("");
const attachedTemplate = ref(""); // name of the Email Template this body came from
const templateSearch = ref("");
const showTemplateDropdown = ref(false);
const loadingTemplates = ref(false);
const templates = ref([]);

// Auto-save state
const saveStatus = ref(""); // "" | "saving" | "saved"
let isReady = false;        // true once the dialog has finished populating
let saveTimer = null;
let savedTimer = null;

// Reset editor content when dialog opens
watch(
	() => props.modelValue,
	(isOpen) => {
		if (isOpen) {
			isReady = false;
			htmlBody.value = props.initialBody || "";
			subject.value = props.initialSubject || "";
			attachedTemplate.value = props.initialTemplate || "";
			templateSearch.value = "";
			saveStatus.value = "";
			if (saveTimer) clearTimeout(saveTimer);
			if (savedTimer) clearTimeout(savedTimer);
			fetchTemplates();
			// Allow edits to trigger auto-save only after the initial values settle
			setTimeout(() => {
				isReady = true;
			}, 0);
		}
	}
);

// Debounced auto-save — fires whenever the subject, body, or template changes
watch([subject, htmlBody, attachedTemplate], () => {
	if (!isReady) return;
	saveStatus.value = "saving";
	if (saveTimer) clearTimeout(saveTimer);
	if (savedTimer) clearTimeout(savedTimer);
	saveTimer = setTimeout(() => {
		emit("save", {
			body: htmlBody.value,
			subject: subject.value,
			template: attachedTemplate.value,
		});
		saveStatus.value = "saved";
		// Fade the "Saved" indicator after a short while
		savedTimer = setTimeout(() => {
			if (saveStatus.value === "saved") saveStatus.value = "";
		}, 2000);
	}, 500);
});

const filteredTemplates = computed(() => {
	const q = (templateSearch.value || "").toLowerCase();
	if (!q) return templates.value;
	return templates.value.filter(
		(t) =>
			t.name.toLowerCase().includes(q) ||
			(t.subject && t.subject.toLowerCase().includes(q))
	);
});

async function fetchTemplates() {
	loadingTemplates.value = true;
	try {
		const data = await frappeGet("/api/resource/Email Template", {
			fields: JSON.stringify(["name", "subject"]),
			limit_page_length: 200,
			order_by: "name asc",
		});
		templates.value = Array.isArray(data) ? data : [];
	} catch (err) {
		console.error("[NotifyAssigneeEditor] Failed to fetch email templates:", err);
		templates.value = [];
	} finally {
		loadingTemplates.value = false;
	}
}

async function selectTemplate(tpl) {
	showTemplateDropdown.value = false;
	templateSearch.value = tpl.name;

	// Fetch the full template to get the HTML body + subject
	try {
		const doc = await frappeGet(`/api/resource/Email Template/${encodeURIComponent(tpl.name)}`, {
			fields: JSON.stringify(["subject", "response_html", "response"]),
		});
		// Prefer response_html; fall back to response (plain text / markdown)
		const body = doc?.response_html || doc?.response || "";
		if (body) {
			htmlBody.value = body;
		}
		// Pre-populate the subject from the template too
		if (doc?.subject) {
			subject.value = doc.subject;
		}
		// Mark this template as attached
		attachedTemplate.value = tpl.name;
	} catch (err) {
		console.error("[NotifyAssigneeEditor] Failed to fetch template content:", err);
	}
}

function detachTemplate() {
	// Detach the template marker only — keep the body/subject the user may have edited.
	attachedTemplate.value = "";
	templateSearch.value = "";
}

function onBlurTemplate() {
	setTimeout(() => {
		showTemplateDropdown.value = false;
	}, 200);
}
</script>
