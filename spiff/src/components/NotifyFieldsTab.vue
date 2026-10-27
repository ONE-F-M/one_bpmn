<template>
	<div class="space-y-5">
		<div
			v-for="list in lists"
			:key="list.key"
			class="space-y-1.5"
		>
			<FormLabel :label="list.label" />
			<div
				v-if="list.entries.length"
				class="flex flex-wrap gap-1.5"
			>
				<Badge
					v-for="entry in list.entries"
					:key="fieldOf(entry)"
					size="lg"
					:label="labelOf(fieldOf(entry))"
				>
					<template #suffix>
						<Button
							variant="ghost"
							size="sm"
							icon="x"
							class="!h-5 !w-5"
							:aria-label="`Remove ${labelOf(fieldOf(entry))}`"
							@click="remove(list.key, entry)"
						/>
					</template>
				</Badge>
			</div>
			<Autocomplete
				:compare-fn="compareOption"
				:model-value="null"
				:options="fieldOptions"
				placeholder="Add field..."
				@update:model-value="(option) => add(list.key, option)"
			/>
			<ErrorMessage
				v-if="list.key === 'facts' && full"
				message="Up to 6 fields. Put the rest in Details."
			/>
			<p class="text-p-sm text-ink-gray-5">{{ list.help }}</p>
		</div>

		<div
			v-if="!isChat"
			class="space-y-1.5"
		>
			<FormControl
				type="checkbox"
				label="Include attachments as links"
				:model-value="attachments === 'true'"
				@update:model-value="(on) => (attachments = on ? 'true' : '')"
			/>
			<p class="text-p-sm text-ink-gray-5">
				Private files open the login page from an email. The composer sends signed links that expire with the task.
			</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { Autocomplete, Badge, Button, ErrorMessage, FormControl, FormLabel } from "frappe-ui";
import { compareOption } from "@/utils/compareOption";
import { MAX_FACTS, fieldOf, parseFieldList, serializeFieldList } from "@/bpmn/shared/notifyFields";
import { useDoctypeFields } from "@/composables/useDoctypeFields";

const VALUE_FIELDTYPES = [
	"Data", "Link", "Dynamic Link", "Select", "Autocomplete", "Date", "Datetime", "Time", "Duration",
	"Int", "Float", "Currency", "Percent", "Rating", "Check", "Phone", "Read Only",
	"Small Text", "Text", "Long Text", "Text Editor",
];

const props = defineProps({
	doctype: { type: String, default: "" },
	layout: { type: String, default: "" },
});

// JSON lists as strings, and "true" or "" for attachments
const facts = defineModel("facts", { type: String });
const details = defineModel("details", { type: String });
const attachments = defineModel("attachments", { type: String });

const { fields, load } = useDoctypeFields(VALUE_FIELDTYPES);
watch(() => props.doctype, load, { immediate: true });

const full = ref(false);
const isChat = computed(() => props.layout === "chat");
const factList = computed(() => parseFieldList(facts.value));
const detailList = computed(() => parseFieldList(details.value));

const lists = computed(() => [
	{
		key: "facts",
		label: isChat.value ? "Summary Fields" : "Key Facts",
		entries: factList.value,
		help: `Up to ${MAX_FACTS}, in this order. Fields of the ${props.doctype}.`,
	},
	...(isChat.value
		? []
		: [{ key: "details", label: "Details Fields", entries: detailList.value, help: "Folded under Details in the email." }]),
]);

// A field picked in either list is not offered again
const available = computed(() => {
	const used = [...factList.value, ...detailList.value].map(fieldOf);
	return fields.value.filter((f) => !used.includes(f.fieldname));
});

function labelOf(fieldname) {
	return fields.value.find((f) => f.fieldname === fieldname)?.label || fieldname;
}

const fieldOptions = computed(() => [
	{
		group: `${props.doctype} fields`,
		items: available.value.map((f) => ({ label: f.label, value: f.fieldname, description: f.fieldname })),
	},
]);

function add(key, option) {
	const fieldname = option?.value;
	if (!fieldname) return;
	if (key === "facts") {
		if (factList.value.length >= MAX_FACTS) {
			full.value = true;
			return;
		}
		facts.value = serializeFieldList([...factList.value, fieldname]);
	} else {
		details.value = serializeFieldList([...detailList.value, fieldname]);
	}
}

function remove(key, entry) {
	if (key === "facts") {
		full.value = false;
		facts.value = serializeFieldList(factList.value.filter((e) => e !== entry));
	} else {
		details.value = serializeFieldList(detailList.value.filter((e) => e !== entry));
	}
}
</script>
