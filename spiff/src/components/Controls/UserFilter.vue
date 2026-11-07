<template>
	<!-- Autocomplete's own popover is hardcoded w-full, so the width has to come
	     from a wrapper — otherwise the trigger and dropdown span the whole toolbar. -->
	<div :class="widthClass">
		<Autocomplete
			:modelValue="modelValue"
			:options="options"
			:loading="loading"
			:placeholder="placeholder"
			:compare-fn="compareOption"
			@update:query="debouncedFetch"
			@update:modelValue="onSelect"
		>
			<template #target="{ togglePopover }">
				<Button
					variant="ghost"
					class="w-full justify-between bg-gray-100 hover:bg-gray-200 border-none"
					:title="modelValue ? `${modelValue.label} (${modelValue.value})` : placeholder"
					@click="togglePopover"
				>
					<span class="truncate font-normal" :class="modelValue ? 'text-gray-700' : 'text-gray-500'">
						{{ modelValue?.label || placeholder }}
					</span>
					<template #suffix>
						<div class="flex items-center gap-1">
							<div
								v-if="modelValue"
								class="p-1 hover:bg-gray-300 rounded-full transition-colors"
								@click.stop="onSelect(null)"
							>
								<FeatherIcon name="x-circle" class="w-3 h-3 text-gray-500" />
							</div>
							<FeatherIcon name="chevron-down" class="w-4 h-4 text-gray-400" />
						</div>
					</template>
				</Button>
			</template>

			<template #item-prefix="{ option }">
				<Avatar :label="option.label" size="sm" />
			</template>
		</Autocomplete>
	</div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue"
import { frappeRequest, Autocomplete, Avatar, Button, FeatherIcon } from "frappe-ui"

const props = defineProps({
	// Selected option: { label, value } where value is the user id (email), or null
	modelValue: {
		type: Object,
		default: null,
	},
	placeholder: {
		type: String,
		default: "Filter by User...",
	},
	widthClass: {
		type: String,
		default: "w-48",
	},
})

const emit = defineEmits(["update:modelValue", "change"])

const options = ref([])
const loading = ref(false)
let fetchTimer = null

onMounted(() => fetchUsers())
onBeforeUnmount(() => clearTimeout(fetchTimer))

// This site has ~1700 enabled users, so the list is searched server-side and
// capped rather than shipped whole and filtered in the browser. PAGE matches
// Autocomplete's own maxOptions — anything beyond it would never be rendered.
// Autocomplete still filters what it is given, on label OR value, so a user the
// server matched by email survives even when the query isn't in their name.
const PAGE = 50

function debouncedFetch(query) {
	clearTimeout(fetchTimer)
	fetchTimer = setTimeout(() => fetchUsers(query), 300)
}

async function fetchUsers(query = "") {
	loading.value = true
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.utils.get_system_users",
			params: { query, limit: PAGE },
		})
		options.value = (response || []).map((u) => ({
			label: u.full_name || u.name,
			value: u.name,
		}))
	} catch (error) {
		console.error("Failed to fetch users:", error)
		options.value = []
	} finally {
		loading.value = false
	}
}

// Autocomplete's built-in comparator is `(a, b) => a.value === b.value`, which
// throws the moment either side is null — and a cleared filter IS null. The
// throw happens inside headlessui's compare, silently aborting the selection,
// so without this the dropdown simply never picks anything up.
function compareOption(a, b) {
	return a?.value === b?.value
}

function onSelect(option) {
	// Autocomplete hands back the whole option; null means the selection was cleared.
	const next = option && option.value ? option : null
	emit("update:modelValue", next)
	emit("change", next)
}
</script>
