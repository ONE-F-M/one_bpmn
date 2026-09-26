<template>
	<!-- Autocomplete's popover is w-full, so the width comes from this wrapper. -->
	<div :class="widthClass">
		<Autocomplete
			:model-value="selected"
			:options="options"
			:placeholder="placeholder"
			:max-options="MAX_OPTIONS"
			:compare-fn="compareOption"
			@update:model-value="onSelect"
		>
			<template #target="{ togglePopover }">
				<Button
					variant="subtle"
					class="w-full justify-between"
					:disabled="disabled"
					:title="modelValue || placeholder"
					@click="togglePopover"
				>
					<span class="truncate font-normal text-gray-800">
						{{ modelValue || placeholder }}
					</span>
					<template #suffix>
						<div class="flex items-center gap-1">
							<div
								v-if="modelValue && !disabled"
								class="p-1 hover:bg-gray-300 rounded-full"
								@click.stop="onSelect(null)"
							>
								<FeatherIcon
									name="x-circle"
									class="w-3 h-3 text-gray-500"
								/>
							</div>
							<FeatherIcon
								name="chevron-down"
								class="w-4 h-4 text-gray-400"
							/>
						</div>
					</template>
				</Button>
			</template>
		</Autocomplete>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { Autocomplete, Button, FeatherIcon } from "frappe-ui"

const props = defineProps({
	modelValue: { type: String, default: "" },
	values: { type: Array, default: () => [] },
	placeholder: { type: String, default: "" },
	disabled: { type: Boolean, default: false },
	widthClass: { type: String, default: "w-full sm:w-48" },
})

const emit = defineEmits(["update:modelValue"])

// Typing narrows the list, so a long one stays usable.
const MAX_OPTIONS = 200

const options = computed(() => props.values.map((value) => ({ label: value, value })))
const selected = computed(() => (props.modelValue ? { label: props.modelValue, value: props.modelValue } : null))

// The default comparator throws on null, which a cleared selection is.
function compareOption(a, b) {
	return a?.value === b?.value
}

function onSelect(option) {
	emit("update:modelValue", option?.value || "")
}
</script>
