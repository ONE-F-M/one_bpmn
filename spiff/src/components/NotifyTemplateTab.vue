<template>
	<div class="space-y-4">
		<div>
			<label class="flex items-center gap-2 text-sm font-medium text-gray-700">
				<input
					v-model="useHtml"
					type="checkbox"
				/>
				Use Email Template or custom HTML
			</label>
			<p class="text-xs text-gray-400 mt-1">
				For existing tasks. The email is built and sent exactly as today: your HTML in the standard frame, cleaned for
				AMP, with today's buttons (the first action is filled; Confirm and Sign open ERPNext) and live status. Tasks
				that already have a template or HTML open with this on.
			</p>
		</div>

		<template v-if="useHtml">
			<div>
				<label class="block text-xs font-medium text-gray-700 mb-1">
					Pre-populate from Email Template
				</label>
				<div class="relative">
					<Icon
						icon="lucide:search"
						class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
					/>
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
							class="px-3 py-2 text-sm cursor-pointer hover:bg-blue-50 text-gray-900 border-b border-gray-50 last:border-b-0"
							@mousedown.prevent="selectTemplate(tpl)"
						>
							<div class="font-medium">{{ tpl.name }}</div>
							<div
								v-if="tpl.subject"
								class="text-xs text-gray-500 mt-0.5"
							>
								{{ tpl.subject }}
							</div>
						</div>
					</div>
					<div
						v-if="showTemplateDropdown && !loadingTemplates && filteredTemplates.length === 0 && templateSearch"
						class="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg"
					>
						<div class="px-3 py-3 text-sm text-gray-400 text-center">No templates found</div>
					</div>
				</div>
				<div class="mt-2">
					<span
						v-if="template"
						class="inline-flex items-center gap-1.5 px-2 py-1 rounded-full bg-green-50 text-green-700 text-xs font-medium border border-green-200"
					>
						<Icon
							icon="lucide:paperclip"
							class="w-3.5 h-3.5"
						/>
						Template attached: {{ template }}
						<button
							type="button"
							class="ml-1 text-green-600 hover:text-green-900"
							title="Detach template"
							@click="detachTemplate"
						>
							<Icon
								icon="lucide:x"
								class="w-3.5 h-3.5"
							/>
						</button>
					</span>
					<span
						v-else
						class="inline-flex items-center gap-1.5 text-xs text-gray-400"
					>
						<Icon
							icon="lucide:paperclip-off"
							class="w-3.5 h-3.5"
						/>
						No template attached
					</span>
				</div>
				<p class="text-xs text-gray-400 mt-1">
					Selecting a template copies its HTML into the editor below. Changes here do not affect the original template.
				</p>
			</div>

			<div>
				<label class="block text-xs font-medium text-gray-700 mb-1">
					HTML Body
				</label>
				<textarea
					v-model="body"
					class="w-full h-64 p-3 font-mono text-sm border border-gray-300 rounded-lg bg-gray-50 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400 resize-y"
					placeholder="Enter notification HTML here..."
					spellcheck="false"
				></textarea>
				<p
					class="text-xs text-gray-400 mt-1"
					v-pre
				>
					Jinja template variables are supported: <code class="bg-gray-100 px-1 rounded">{{ doc.name }}</code>,
					<code class="bg-gray-100 px-1 rounded">{{ doc.owner }}</code>, etc.
				</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { Icon } from "@iconify/vue";
import { frappeGet } from "@/bpmn/shared/frappeResource";

const useHtml = defineModel("useHtml", { type: Boolean });
const template = defineModel("template", { type: String });
const body = defineModel("body", { type: String });
const subject = defineModel("subject", { type: String });

const templateSearch = ref("");
const showTemplateDropdown = ref(false);
const loadingTemplates = ref(false);
const templates = ref([]);

const filteredTemplates = computed(() => {
	const q = (templateSearch.value || "").toLowerCase();
	if (!q) return templates.value;
	return templates.value.filter(
		(t) =>
			t.name.toLowerCase().includes(q) ||
			(t.subject && t.subject.toLowerCase().includes(q))
	);
});

onMounted(fetchTemplates);

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
		const html = doc?.response_html || doc?.response || "";
		if (html) {
			body.value = html;
		}
		if (doc?.subject) {
			subject.value = doc.subject;
		}
		template.value = tpl.name;
	} catch (err) {
		console.error("[NotifyAssigneeEditor] Failed to fetch template content:", err);
	}
}

function detachTemplate() {
	// Detach the template marker only; keep the body/subject the user may have edited.
	template.value = "";
	templateSearch.value = "";
}

function onBlurTemplate() {
	setTimeout(() => {
		showTemplateDropdown.value = false;
	}, 200);
}
</script>

