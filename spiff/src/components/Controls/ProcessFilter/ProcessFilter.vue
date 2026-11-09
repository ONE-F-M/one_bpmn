<template>
	<NestedPopover>
		<template #target>
			<div class="flex items-center w-fit">
				<Button :label="'Filter'" :class="filters.length ? 'rounded-r-none' : ''">
					<template #prefix>
						<Icon icon="lucide:list-filter" class="h-4 w-4" />
					</template>
					<template v-if="filters.length" #suffix>
						<span
							class="flex h-5 w-5 items-center justify-center rounded-[5px] bg-white pt-px text-xs font-medium text-gray-800 shadow-sm"
						>
							{{ filters.length }}
						</span>
					</template>
				</Button>
				<Tooltip v-if="filters.length" :text="'Clear all filters'">
					<div>
						<Button class="rounded-l-none border-l" @click.stop="clearAll">
							<Icon icon="lucide:x" class="h-4 w-4" />
						</Button>
					</div>
				</Tooltip>
			</div>
		</template>
		<template #body>
			<div class="my-2 rounded-lg border border-gray-100 bg-white shadow-xl">
				<div class="min-w-72 p-2 sm:min-w-[400px]">
					<!-- Active filter rows -->
					<div
						v-for="(f, i) in filters"
						:key="f.field || i"
						class="mb-3 flex items-center justify-between gap-2"
					>
						<div class="flex items-center gap-2 flex-1">
							<div class="w-12 pl-2 text-end text-base text-gray-600">
								{{ i === 0 ? "Where" : "And" }}
							</div>
							<div class="min-w-[120px]">
								<FormControl
									type="select"
									:modelValue="f.field"
									:options="availableFieldOptions(i)"
									@update:modelValue="(v) => updateField(i, v)"
								/>
							</div>
							<div>
								<FormControl
									type="select"
									:modelValue="f.operator"
									:options="operatorOptions"
									@update:modelValue="(v) => updateOperator(i, v)"
								/>
							</div>
							<div class="min-w-[140px] flex-1">
								<FormControl
									type="select"
									:modelValue="f.value"
									:options="valueOptions(f.field)"
									:placeholder="'Value'"
									@update:modelValue="(v) => updateValue(i, v)"
								/>
							</div>
						</div>
						<Button variant="ghost" @click="removeFilter(i)">
							<Icon icon="lucide:x" class="h-4 w-4" />
						</Button>
					</div>

					<!-- Empty state -->
					<div
						v-if="!filters.length"
						class="mb-3 flex h-7 items-center px-3 text-sm text-gray-600"
					>
						Empty - Choose a field to filter by
					</div>

					<!-- Actions -->
					<div class="flex items-center justify-between gap-2">
						<Button
							class="!text-gray-600"
							variant="ghost"
							:label="'Add Filter'"
							:disabled="!unusedFields.length"
							@click="addFilter"
						>
							<template #prefix>
								<Icon icon="lucide:plus" class="h-4 w-4" />
							</template>
						</Button>
						<Button
							v-if="filters.length"
							class="!text-gray-600"
							variant="ghost"
							:label="'Clear all filters'"
							@click="clearAll"
						/>
					</div>
				</div>
			</div>
		</template>
	</NestedPopover>
</template>

<script setup>
import { computed } from "vue"
import { Button, FormControl, NestedPopover, Tooltip } from "frappe-ui"
import { Icon } from "@iconify/vue"

const props = defineProps({
	// Array of { field, operator, value }
	modelValue: {
		type: Array,
		default: () => [],
	},
	// Owner options: [{ label, value }]
	ownerOptions: {
		type: Array,
		default: () => [],
	},
})

const emit = defineEmits(["update:modelValue"])

const fieldDefs = {
	process_owner: { label: "Process Owner" },
	status: { label: "Status" },
}

const operatorOptions = [
	{ label: "Equals", value: "equals" },
	{ label: "Not Equals", value: "not_equals" },
]

const statusValueOptions = [
	{ label: "Active", value: "Active" },
	{ label: "Inactive", value: "Inactive" },
	{ label: "No Process Maps", value: "No Process Maps" },
]

const filters = computed(() => props.modelValue)

// Fields not yet used by any filter row
const unusedFields = computed(() =>
	Object.keys(fieldDefs).filter((key) => !filters.value.some((f) => f.field === key))
)

// For a given row, the field options it may choose: its own field + any unused field
function availableFieldOptions(index) {
	const current = filters.value[index]?.field
	return Object.entries(fieldDefs)
		.filter(([key]) => key === current || unusedFields.value.includes(key))
		.map(([value, def]) => ({ label: def.label, value }))
}

function valueOptions(field) {
	if (field === "status") return statusValueOptions
	if (field === "process_owner") return props.ownerOptions
	return []
}

function defaultValue(field) {
	const opts = valueOptions(field)
	return opts.length ? opts[0].value : ""
}

function emitFilters(next) {
	emit("update:modelValue", next)
}

function addFilter() {
	const field = unusedFields.value[0]
	if (!field) return
	emitFilters([
		...filters.value,
		{ field, operator: "equals", value: defaultValue(field) },
	])
}

function updateField(index, field) {
	const next = filters.value.map((f, i) =>
		i === index ? { ...f, field, value: defaultValue(field) } : f
	)
	emitFilters(next)
}

function updateOperator(index, operator) {
	emitFilters(filters.value.map((f, i) => (i === index ? { ...f, operator } : f)))
}

function updateValue(index, value) {
	emitFilters(filters.value.map((f, i) => (i === index ? { ...f, value } : f)))
}

function removeFilter(index) {
	emitFilters(filters.value.filter((_, i) => i !== index))
}

function clearAll() {
	emitFilters([])
}
</script>
