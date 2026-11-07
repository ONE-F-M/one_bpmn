<template>
	<div
		class="record-picker w-full"
	>
		<label v-if="label" class="mb-1.5 block text-xs text-ink-gray-5">{{ label }}</label>
		<Autocomplete
			:modelValue="selection"
			:options="listed"
			:multiple="multiple"
			:loading="loading || fetching"
			:placeholder="placeholder"
			:compare-fn="compareOption"
			:body-classes="multiple ? 'record-picker-body record-picker-body--multi' : 'record-picker-body'"
			@update:query="onQuery"
			@update:modelValue="onSelect"
		>
			<template #target="{ togglePopover }">
				<div
					:id="id"
					class="record-picker-field"
					role="combobox"
					tabindex="0"
					@click="toggle(togglePopover)"
					@keydown.enter.prevent="toggle(togglePopover)"
					@keydown.down.prevent="toggle(togglePopover)"
				>
					<span
						v-if="multiple"
						class="record-picker-tags"
					>
						<span
							v-for="value in selected"
							:key="value"
							class="record-picker-tag"
						>
							<span class="record-picker-tag-text">{{ labelOf(value) }}</span>
							<button
								type="button"
								class="record-picker-tag-remove"
								:title="translate('Remove')"
								@mousedown.prevent
								@click.stop="remove(value)"
							>
								x
							</button>
						</span>
						<span
							v-if="!hasValue"
							class="record-picker-text record-picker-placeholder"
						>
							{{ placeholder }}
						</span>
					</span>
					<span
						v-else
						class="record-picker-text"
						:class="{ 'record-picker-placeholder': !hasValue }"
					>
						{{ displayText }}
					</span>
					<button
						v-if="hasValue && !multiple"
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
				<template v-else>
					<Button
						v-if="canCreate"
						class="w-full"
						variant="ghost"
						:loading="saving"
						@mousedown.prevent
						@click.stop="startCreate"
					>
						{{ translate("Create") }} "{{ query.trim() }}"
					</Button>
				</template>
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
	// "live" stores the text on every keystroke; "blur" stores it when the picker closes without a pick
	allowFreeText: { type: String, default: "" },
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
let closeWatcher = null
let toggler = null
let justPicked = false

const selected = computed(() => valuesOf(props.modelValue))
const listed = computed(() => (props.multiple ? shown.value.filter((o) => !selected.value.includes(o.value)) : shown.value))
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
	const previous = query.value
	query.value = text
	if (props.allowFreeText && !props.multiple) keepTyped(previous, text)
	if (props.localSearch || props.options) return
	clearTimeout(timer)
	timer = setTimeout(() => load(text), SEARCH_DELAY)
}

// Typing alone changes the value: the Autocomplete empties its query only after a pick.
function keepTyped(previous, text) {
	if (text === "" && justPicked) {
		justPicked = false
		return
	}
	if (props.allowFreeText === "live") {
		emit("update:modelValue", text)
		emit("select", null)
	} else if (text.trim()) {
		watchForClose()
	}
}

function watchForClose() {
	if (closeWatcher) return
	closeWatcher = setInterval(() => {
		if (document.querySelector(".record-picker-body")) return
		clearInterval(closeWatcher)
		closeWatcher = null
		commitTyped()
	}, 100)
}

function commitTyped() {
	const typed = query.value.trim()
	const cancelled = justPicked || creating.value || saving.value
	justPicked = false
	if (!cancelled && typed && typed !== props.modelValue) {
		emit("update:modelValue", typed)
		emit("select", null)
	}
}

function onKeydown(event) {
	if (props.allowFreeText !== "blur" || !closeWatcher || !toggler) return
	if (event.key !== "Escape" && event.key !== "Tab") return
	event.preventDefault()
	event.stopPropagation()
	clearInterval(closeWatcher)
	closeWatcher = null
	if (event.key === "Tab") commitTyped()
	else query.value = ""
	toggler()
}

function toggle(togglePopover) {
	toggler = togglePopover
	togglePopover()
}

function onSelect(next) {
	justPicked = query.value !== ""
	const values = valuesOf(next)
	const picked = props.multiple ? next || [] : next || null
	emit("update:modelValue", props.multiple ? values : values[0] || "")
	emit("select", picked)
}

function clear() {
	emit("update:modelValue", props.multiple ? [] : "")
	emit("select", props.multiple ? [] : null)
}

function labelOf(value) {
	return shown.value.find((o) => o.value === value)?.label || value
}

function remove(value) {
	const next = selected.value.filter((v) => v !== value)
	emit("update:modelValue", next)
	emit("select", next)
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
onMounted(() => {
	load()
	document.addEventListener("keydown", onKeydown, true)
})
onBeforeUnmount(() => {
	clearTimeout(timer)
	clearInterval(closeWatcher)
	document.removeEventListener("keydown", onKeydown, true)
})
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
.record-picker-tags {
	display: flex;
	flex: 1;
	flex-wrap: wrap;
	gap: 0.25rem;
	min-width: 0;
}
.record-picker-tag {
	display: inline-flex;
	align-items: center;
	gap: 0.25rem;
	max-width: 100%;
	padding: 0 0.375rem;
	border-radius: 0.25rem;
	background: var(--surface-gray-4, #e2e2e2);
}
.record-picker-tag-text {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.record-picker-tag-remove {
	line-height: 1;
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
	max-width: min(var(--reka-popover-trigger-width, 100vw), calc(100vw - 3rem));
}
.record-picker-body--multi .border-t {
	display: none;
}
.record-picker-body [role="listbox"] {
	max-height: min(15rem, 50vh);
	overscroll-behavior: contain;
}
</style>
