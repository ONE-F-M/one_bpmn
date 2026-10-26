<template>
	<div class="space-y-5">
		<div
			v-for="list in lists"
			:key="list.key"
		>
			<span class="block text-xs font-medium text-gray-700 mb-2">{{ list.label }}</span>
			<div class="flex flex-wrap gap-2 mb-2">
				<span
					v-for="entry in list.entries"
					:key="fieldOf(entry)"
					class="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-gray-100 text-xs text-gray-800"
				>
					{{ labelOf(fieldOf(entry)) }}
					<button
						type="button"
						class="text-gray-500 hover:text-gray-900"
						:aria-label="`Remove ${labelOf(fieldOf(entry))}`"
						@click="remove(list.key, entry)"
					>
						<Icon
							icon="lucide:x"
							class="w-3 h-3"
						/>
					</button>
				</span>
			</div>
			<select
				:aria-label="`Add ${list.label}`"
				class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
				:value="''"
				@change="add(list.key, $event)"
			>
				<option value="">Add field...</option>
				<optgroup :label="`${doctype} fields`">
					<option
						v-for="f in available"
						:key="f.fieldname"
						:value="f.fieldname"
					>
						{{ f.label }} ({{ f.fieldname }})
					</option>
				</optgroup>
			</select>
			<p
				v-if="list.key === 'facts' && full"
				class="text-xs text-red-600 mt-1"
			>
				Up to 6 fields. Put the rest in Details.
			</p>
			<p class="text-xs text-gray-400 mt-1">{{ list.help }}</p>
		</div>

		<div v-if="!isChat">
			<label class="flex items-center gap-2 text-sm font-medium text-gray-700">
				<input
					type="checkbox"
					:checked="attachments === 'true'"
					@change="attachments = $event.target.checked ? 'true' : ''"
				/>
				Include attachments as links
			</label>
			<p class="text-xs text-gray-400 mt-1">
				Private files open the login page from an email. The composer sends signed links that expire with the task.
			</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { Icon } from "@iconify/vue";
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

function add(key, event) {
	const fieldname = event.target.value;
	event.target.value = "";
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
