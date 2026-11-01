<template>
	<div class="space-y-4">
		<FormControl
			type="text"
			label="Email Address"
			placeholder="e.g. john@example.com, jane@example.com"
			description="Direct email addresses, comma-separated."
			:model-value="values.emailTo"
			@update:model-value="(value) => emit('update', 'emailTo', value)"
		/>

		<div class="space-y-1.5">
			<FormLabel label="Document Field" />
			<template v-if="doctype">
				<NotifyTagBox
					:tags="docFieldTags"
					:options="docFieldOptions"
					placeholder="Add field..."
					@add="(option) => addTo('emailToDocFields', option.value)"
					@remove="(fieldname) => removeFrom('emailToDocFields', fieldname)"
				/>
				<p class="text-p-sm text-ink-gray-5">
					Fields that hold a user or an email address. "Created By" sends to whoever created the document.
				</p>
			</template>
			<p
				v-else
				class="rounded bg-surface-gray-2 p-2 text-p-sm text-ink-gray-6"
			>
				Tick Based on a Specific Doctype Record on the Sending tab to pick fields.
			</p>
		</div>

		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
			<Autocomplete
				:compare-fn="compareOption"
				label="Table Field"
				:placeholder="tablePlaceholder"
				:options="tableOptions"
				:model-value="values.emailToTableField || null"
				@update:model-value="setTable"
			/>
			<Autocomplete
				:compare-fn="compareOption"
				label="Row User Field"
				:placeholder="values.emailToTableField ? 'Rows default to &quot;user&quot;' : 'Select a Table Field first'"
				:options="rowUserOptions"
				:model-value="values.emailToTableUserField || null"
				@update:model-value="(option) => emit('update', 'emailToTableUserField', option?.value || '')"
			/>
		</div>

		<div class="space-y-1.5">
			<FormLabel label="Role" />
			<NotifyTagBox
				:tags="roleTags"
				:options="roleOptions"
				placeholder="Add role..."
				@add="(option) => addTo('emailToRoles', option.value)"
				@remove="(role) => removeFrom('emailToRoles', role)"
			/>
			<p class="text-p-sm text-ink-gray-5">All users in these roles receive the email.</p>
		</div>

		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
			<FormControl
				type="text"
				label="CC"
				placeholder="Comma-separated email addresses"
				:model-value="values.emailCc"
				@update:model-value="(value) => emit('update', 'emailCc', value)"
			/>
			<FormControl
				type="text"
				label="BCC"
				placeholder="Comma-separated email addresses"
				:model-value="values.emailBcc"
				@update:model-value="(value) => emit('update', 'emailBcc', value)"
			/>
		</div>

		<ErrorMessage
			v-if="error"
			:message="error"
		/>
	</div>
</template>

<script setup>
import { computed, watch } from "vue";
import { Autocomplete, ErrorMessage, FormControl, FormLabel } from "frappe-ui";
import NotifyTagBox from "@/components/NotifyTagBox.vue";
import { splitList } from "@/bpmn/shared/emailNotification";
import { compareOption } from "@/utils/compareOption";

const props = defineProps({
	// the dialog's working copy of the email attributes
	values: { type: Object, required: true },
	// the DocType the email is based on; empty when the record toggle is off
	doctype: { type: String, default: "" },
	options: { type: Object, required: true },
	error: { type: String, default: "" },
});

const emit = defineEmits(["update"]);

watch(() => props.doctype, (doctype) => props.options.loadDoctypeFields(doctype), { immediate: true });

const childDoctype = computed(
	() => props.options.tableFields.value.find((f) => f.fieldname === props.values.emailToTableField)?.options || ""
);
watch(childDoctype, (doctype) => props.options.loadRowUserFields(doctype), { immediate: true });

const fieldLabel = (f) => `${f.label || f.fieldname} (${f.fieldname})`;

const docFieldTags = computed(() =>
	splitList(props.values.emailToDocFields).map((fieldname) => {
		const field = props.options.docFields.value.find((f) => f.fieldname === fieldname);
		return { key: fieldname, label: field?.label || fieldname };
	})
);
const docFieldOptions = computed(() => {
	const used = splitList(props.values.emailToDocFields);
	return props.options.docFields.value
		.filter((f) => !used.includes(f.fieldname))
		.map((f) => ({ label: f.kind === "user" ? `${fieldLabel(f)} · user` : fieldLabel(f), value: f.fieldname }));
});

const roleTags = computed(() => splitList(props.values.emailToRoles).map((role) => ({ key: role, label: role })));
const roleOptions = computed(() => {
	const used = splitList(props.values.emailToRoles);
	return props.options.roles.value.filter((r) => !used.includes(r)).map((r) => ({ label: r, value: r }));
});

const tableOptions = computed(() => props.options.tableFields.value.map((f) => ({ label: fieldLabel(f), value: f.fieldname })));
const rowUserOptions = computed(() =>
	props.options.rowUserFields.value.map((f) => ({ label: fieldLabel(f), value: f.fieldname }))
);
const tablePlaceholder = computed(() => {
	if (!props.doctype) return "Select a DocType first";
	return tableOptions.value.length ? "Select a Table Field..." : "No Table/Table MultiSelect fields found";
});

function addTo(name, value) {
	if (value) emit("update", name, [...splitList(props.values[name]), value].join(","));
}

function removeFrom(name, value) {
	emit("update", name, splitList(props.values[name]).filter((v) => v !== value).join(","));
}

// the row field belongs to the table it was picked from
function setTable(option) {
	emit("update", "emailToTableField", option?.value || "");
	emit("update", "emailToTableUserField", "");
}
</script>
