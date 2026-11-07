<template>
	<div class="record-picker w-full">
		<label v-if="label" class="mb-1.5 block text-xs text-ink-gray-5">{{ label }}</label>
		<Autocomplete
			:modelValue="selection"
			:options="shown"
			:multiple="multiple"
			:loading="loading || fetching"
			:placeholder="placeholder"
			:compare-fn="compareOption"
			body-classes="record-picker-body"
			@update:query="onQuery"
			@update:modelValue="onSelect"
		>
			<template #target="{ togglePopover }">
				<div
					:id="id"
					class="record-picker-field"
					role="combobox"
					tabindex="0"
					@click="togglePopover()"
					@keydown.enter.prevent="togglePopover()"
					@keydown.down.prevent="togglePopover()"
				>
					<span
						class="record-picker-text"
						:class="{ 'record-picker-placeholder': !hasValue }"
					>
						{{ displayText }}
					</span>
					<button
						v-if="hasValue"
						type="button"
						class="record-picker-clear"
						:title="translate('Clear')"
						:aria-label="translate('Clear')"
						@click.stop="clear"
					>
						<FeatherIcon name="x" class="h-3 w-3" />
					</button>
					<FeatherIcon name="chevron-down" class="h-4 w-4 flex-shrink-0 text-ink-gray-5" />
				</div>
			</template>

			<template #item-prefix="{ option }">
				<span
					v-if="option.style"
					class="wfs-dot"
					:class="`wfs-dot--${option.style.toLowerCase()}`"
				/>
				<FeatherIcon
					v-else-if="multiple"
					name="check"
					class="h-4 w-4"
					:class="isChosen(option) ? 'text-ink-gray-7' : 'opacity-0'"
				/>
			</template>

			<template v-if="canCreate || creating" #footer>
				<div v-if="creating" class="p-1">
					<slot
						name="create"
						:query="createName"
						:done="onCreated"
						:cancel="() => (creating = false)"
					/>
				</div>
				<Button
					v-else
					class="w-full"
					variant="ghost"
					:loading="saving"
					@mousedown.prevent
					@click.stop="startCreate"
				>
					{{ translate("Create") }} "{{ query.trim() }}"
				</Button>
			</template>
		</Autocomplete>

		<p v-if="error" class="record-picker-error" role="alert">{{ error }}</p>
		<p v-else-if="missing" class="record-picker-warn">
			{{ missingText }}
			<button v-if="createRecord" type="button" class="underline" @click="startCreate">{{ translate("Create it") }}</button>
		</p>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, useSlots, watch } from "vue"
import { Autocomplete, Button, FeatherIcon } from "frappe-ui"
import { compareOption } from "@/utils/compareOption"
import { serverMessage } from "@/utils/serverMessage"
import { SEARCH_DELAY, canCreateRecord, isMissing, valuesOf } from "@/utils/recordPicker"

const props = defineProps({
	modelValue: { type: [String, Array], default: "" },
	multiple: { type: Boolean, default: false },
	id: { type: String, default: undefined },
	placeholder: { type: String, default: "" },
	// Static [{ label, value }] list, searched in the browser
	options: { type: Array, default: null },
	// async (query) => [{ label, value, style? }]; called again on every search unless localSearch is set
	fetchOptions: { type: Function, default: null },
	label: { type: String, default: "" },
	loading: { type: Boolean, default: false },
	localSearch: { type: Boolean, default: false },
	// async (name) => name; shows a Create row for a name that matches no option
	createRecord: { type: Function, default: null },
	missingText: { type: String, default: "" },
	translate: { type: Function, default: (text) => text },
})
const emit = defineEmits(["update:modelValue", "select"])
const slots = useSlots()

const shown = ref([])
const fetching = ref(false)
const query = ref("")
const creating = ref(false)
const createName = ref("")
const saving = ref(false)
const error = ref("")
let timer = null

const selected = computed(() => valuesOf(props.modelValue))
const hasValue = computed(() => selected.value.length > 0)
const selection = computed(() => (props.multiple ? selected.value : props.modelValue || null))
const displayText = computed(() => {
	if (!hasValue.value) return props.placeholder
	return selected.value.map((v) => shown.value.find((o) => o.value === v)?.label || v).join(", ")
})
const canCreate = computed(
	() => Boolean(props.createRecord || slots.create) && canCreateRecord(query.value, shown.value),
)
const missing = computed(
	() =>
		(props.localSearch || Boolean(props.options)) &&
		!props.multiple &&
		Boolean(props.missingText) &&
		isMissing(props.modelValue, shown.value),
)

async function load(text = "") {
	if (!props.fetchOptions) return
	fetching.value = true
	try {
		shown.value = (await props.fetchOptions(text)) || []
		error.value = ""
	} catch (err) {
		shown.value = []
		error.value = serverMessage(err)
	} finally {
		fetching.value = false
	}
}

function onQuery(text) {
	query.value = text
	if (props.localSearch || props.options) return
	clearTimeout(timer)
	timer = setTimeout(() => load(text), SEARCH_DELAY)
}

function onSelect(next) {
	const values = valuesOf(next)
	const picked = props.multiple ? next || [] : next || null
	emit("update:modelValue", props.multiple ? values : values[0] || "")
	emit("select", picked)
}

function clear() {
	emit("update:modelValue", props.multiple ? [] : "")
	emit("select", props.multiple ? [] : null)
}

function isChosen(option) {
	return selected.value.includes(option.value)
}

async function startCreate() {
	createName.value = (query.value || props.modelValue || "").trim()
	if (slots.create) {
		creating.value = true
		return
	}
	saving.value = true
	error.value = ""
	try {
		const name = await props.createRecord(createName.value)
		onCreated({ name })
	} catch (err) {
		error.value = serverMessage(err)
	} finally {
		saving.value = false
	}
}

function onCreated(record) {
	creating.value = false
	shown.value = [...shown.value, { label: record.name, value: record.name, style: record.style }]
	const value = props.multiple ? [...selected.value, record.name] : record.name
	emit("update:modelValue", value)
	emit("select", value)
}

watch(
	() => props.options,
	(next) => (shown.value = next || []),
	{ immediate: true },
)
watch(
	() => props.fetchOptions,
	() => load(query.value),
)
onMounted(() => load())
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.record-picker-field {
	display: flex;
	width: 100%;
	align-items: center;
	gap: 0.5rem;
	min-height: 1.75rem;
	padding: 0.25rem 0.5rem;
	border: 1px solid transparent;
	border-radius: 0.25rem;
	background: var(--surface-gray-2, #f3f3f3);
	cursor: pointer;
}
.record-picker-field:focus {
	outline: none;
	border-color: var(--outline-gray-4, #999);
}
.record-picker-text {
	flex: 1;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.record-picker-placeholder {
	color: var(--ink-gray-4, #999);
}
.record-picker-clear {
	display: inline-flex;
	padding: 0.125rem;
	border-radius: 9999px;
}
.record-picker-error {
	margin-top: 0.25rem;
	font-size: 0.75rem;
	color: #b3261e;
}
.record-picker-warn {
	margin-top: 0.25rem;
	font-size: 0.75rem;
	color: #8a5300;
}
</style>

<style>
.record-picker-body {
	max-width: calc(100vw - 3rem);
}
.record-picker-body [role="listbox"] {
	max-height: min(15rem, 50vh);
	overscroll-behavior: contain;
}
</style>
