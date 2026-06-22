<template>
	<Dialog v-model="open" :options="{ title: 'Notification Editor', size: '4xl' }">
		<template #body-content>
			<div class="space-y-4">
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
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="cancel">Cancel</Button>
				<Button variant="solid" @click="save">Save</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, watch, computed } from "vue";
import { Icon } from "@iconify/vue";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	initialBody: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "save"]);

const open = computed({
	get: () => props.modelValue,
	set: (v) => emit("update:modelValue", v),
});

const htmlBody = ref("");
const templateSearch = ref("");
const showTemplateDropdown = ref(false);
const loadingTemplates = ref(false);
const templates = ref([]);

// Reset editor content when dialog opens
watch(
	() => props.modelValue,
	(isOpen) => {
		if (isOpen) {
			htmlBody.value = props.initialBody || "";
			templateSearch.value = "";
			fetchTemplates();
		}
	}
);

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
		const fields = encodeURIComponent(JSON.stringify(["name", "subject"]));
		const url = `/api/resource/Email Template?fields=${fields}&limit_page_length=200&order_by=name asc`;
		const json = await frappeRequest({ url });
		templates.value = json?.data || [];
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

	// Fetch the full template to get the HTML body
	try {
		const fields = encodeURIComponent(JSON.stringify(["response_html", "response"]));
		const url = `/api/resource/Email Template/${encodeURIComponent(tpl.name)}?fields=${fields}`;
		const json = await frappeRequest({ url });
		const doc = json?.data || {};
		// Prefer response_html; fall back to response (plain text / markdown)
		const body = doc.response_html || doc.response || "";
		if (body) {
			htmlBody.value = body;
		}
	} catch (err) {
		console.error("[NotifyAssigneeEditor] Failed to fetch template content:", err);
	}
}

function onBlurTemplate() {
	setTimeout(() => {
		showTemplateDropdown.value = false;
	}, 200);
}

function save() {
	emit("save", htmlBody.value);
	open.value = false;
}

function cancel() {
	open.value = false;
}
</script>
