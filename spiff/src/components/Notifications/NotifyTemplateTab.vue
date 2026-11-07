<template>
	<div class="space-y-4">
		<div class="space-y-1.5">
			<FormControl
				v-model="useHtml"
				type="checkbox"
				label="Use Email Template or custom HTML"
			/>
			<p class="text-p-sm text-ink-gray-5">
				For existing tasks. The email is built and sent exactly as today: your HTML in the standard frame, cleaned for
				AMP, with today's buttons (the first action is filled; Confirm and Sign open ERPNext) and live status. Tasks
				that already have a template or HTML open with this on.
			</p>
		</div>

		<template v-if="useHtml">
			<div class="space-y-1.5">
				<Autocomplete
					:compare-fn="compareOption"
					label="Pre-populate from Email Template"
					placeholder="Search email templates..."
					:model-value="template || null"
					:options="templateOptions"
					:loading="loadingTemplates"
					@update:model-value="selectTemplate"
				/>
				<div>
					<Badge
						v-if="template"
						theme="green"
						size="lg"
					>
						<template #prefix>
							<FeatherIcon
								name="paperclip"
								class="h-3.5 w-3.5"
							/>
						</template>
						Template attached: {{ template }}
						<template #suffix>
							<Button
								variant="ghost"
								size="sm"
								icon="x"
								class="!h-5 !w-5"
								aria-label="Detach template"
								@click="detachTemplate"
							/>
						</template>
					</Badge>
					<span
						v-else
						class="text-p-sm text-ink-gray-5"
					>No template attached</span>
				</div>
				<p class="text-p-sm text-ink-gray-5">
					The email uses this task's subject and HTML. When either is empty, it uses the attached template's latest subject or HTML at send time. Editing here does not detach the template.
				</p>
			</div>

			<FormControl
				v-model="body"
				type="textarea"
				label="HTML Body"
				:rows="14"
				class="[&_textarea]:font-mono"
				placeholder="Enter notification HTML here..."
				spellcheck="false"
			>
				<template #description>
					<p
						class="text-p-sm text-ink-gray-5"
						v-pre
					>
						Jinja template variables are supported: <code>{{ doc.name }}</code>, <code>{{ doc.owner }}</code>, etc.
					</p>
				</template>
			</FormControl>
		</template>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { Autocomplete, Badge, Button, FeatherIcon, FormControl } from "frappe-ui";
import { compareOption } from "@/utils/compareOption";
import { frappeGet } from "@/bpmn/shared/frappeResource";

const useHtml = defineModel("useHtml", { type: Boolean });
const template = defineModel("template", { type: String });
const body = defineModel("body", { type: String });
const subject = defineModel("subject", { type: String });

const loadingTemplates = ref(false);
const templates = ref([]);

const templateOptions = computed(() =>
	templates.value.map((t) => ({ label: t.name, value: t.name, description: t.subject || "" }))
);

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

async function selectTemplate(option) {
	if (!option?.value) return;

	// Fetch the full template to get the HTML body + subject
	try {
		const doc = await frappeGet(`/api/resource/Email Template/${encodeURIComponent(option.value)}`, {
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
		template.value = option.value;
	} catch (err) {
		console.error("[NotifyAssigneeEditor] Failed to fetch template content:", err);
	}
}

function detachTemplate() {
	// Detach the template marker only; keep the body/subject the user may have edited.
	template.value = "";
}
</script>

