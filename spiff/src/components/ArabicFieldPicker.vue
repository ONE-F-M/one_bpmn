<template>
	<!-- pe-4 keeps the list off the screen edge on a phone, so it stays inside the dialog -->
	<Popover
		placement="bottom-start"
		popover-class="pe-4"
	>
		<template #target="{ togglePopover }">
			<Button
				size="sm"
				:theme="arabicField ? 'blue' : 'gray'"
				:variant="arabicField ? 'solid' : 'subtle'"
				class="!h-5 !px-1 text-[10px] font-bold"
				:title="markTitle"
				:aria-label="markTitle"
				@click="togglePopover()"
			>
				AR
			</Button>
		</template>
		<template #body-main="{ close }">
			<div
				role="listbox"
				aria-label="Arabic value"
				class="max-h-[min(20rem,60vh)] w-[min(20rem,calc(100vw-2rem))] space-y-0.5 overflow-y-auto p-2"
			>
				<p class="px-1.5 pb-1 text-p-sm text-ink-gray-7">
					Arabic value for <b>{{ field.label }}</b>
				</p>
				<Button
					v-for="option in options"
					:key="option.value"
					:variant="option.value === arabicField ? 'subtle' : 'ghost'"
					:theme="option.value === arabicField ? 'blue' : 'gray'"
					class="!h-auto w-full !justify-start !py-1.5 text-left"
					role="option"
					:aria-selected="option.value === arabicField"
					@click="pick(option.value, close)"
				>
					<span class="flex min-w-0 flex-col items-start">
						<span class="whitespace-normal">{{ option.label }}</span>
						<span class="whitespace-normal break-all text-p-xs text-ink-gray-5">{{ option.sub }}</span>
					</span>
				</Button>
				<p
					v-if="!candidates.length"
					class="px-1.5 pt-1 text-p-sm text-ink-gray-5"
				>
					No Arabic field on this document or its linked documents
				</p>
			</div>
		</template>
	</Popover>
</template>

<script setup>
import { computed } from "vue";
import { Button, Popover } from "frappe-ui";

const props = defineProps({
	// { fieldname, label }
	field: { type: Object, required: true },
	// [{ fieldname, label }] from get_email_fields
	candidates: { type: Array, default: () => [] },
});

// a fieldname, or [fieldname, arabic_fieldname] once an Arabic field is picked
const entry = defineModel({ type: [String, Array], required: true });

const arabicField = computed(() => (Array.isArray(entry.value) ? entry.value[1] : ""));

const markTitle = computed(() => {
	const picked = props.candidates.find((c) => c.fieldname === arabicField.value);
	return picked ? `Arabic from ${picked.label}` : "No Arabic field picked: the Arabic email shows the English value";
});

const options = computed(() => [
	{ value: "", label: "Same as English", sub: "The Arabic email shows the English value" },
	...props.candidates.map((c) => ({ value: c.fieldname, label: c.label, sub: c.fieldname })),
]);

function pick(arabicFieldname, close) {
	entry.value = arabicFieldname ? [props.field.fieldname, arabicFieldname] : props.field.fieldname;
	close();
}
</script>
