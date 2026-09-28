<template>
	<div class="space-y-2">
		<FormControl
			type="checkbox"
			:label="__('Include earlier conversation')"
			:model-value="enabled"
			@update:model-value="toggle"
		/>
		<p class="text-xs text-gray-500">
			{{ __("The agent sees these messages as if they already happened, then gets the user prompt.") }}
		</p>

		<div
			v-if="enabled"
			class="border border-gray-200 rounded-md p-3 space-y-3"
		>
			<div class="space-y-2">
				<div class="flex items-center justify-between gap-2">
					<span class="text-sm font-medium text-gray-700">{{ __("Load from a conversation") }}</span>
					<Button
						v-if="picked"
						size="sm"
						variant="ghost"
						:label="__('Back to the list')"
						@click="picked = null"
					/>
				</div>

				<template v-if="!picked">
					<FormControl
						type="text"
						:placeholder="__('Search by title or user')"
						:model-value="term"
						@update:model-value="onSearch"
					/>
					<div class="max-h-48 overflow-auto divide-y divide-gray-100 border border-gray-100 rounded">
						<button
							v-for="c in conversations"
							:key="c.name"
							type="button"
							class="w-full text-left px-2 py-1.5 hover:bg-gray-50"
							@click="pick(c)"
						>
							<div class="text-sm text-gray-900 truncate">{{ plain(c.title) || c.name }}</div>
							<div class="text-xs text-gray-500">{{ c.owner }} · {{ dayjs(c.modified).format("MMM D, HH:mm") }}</div>
						</button>
						<p
							v-if="!conversations.length && !loading"
							class="text-xs text-gray-500 px-2 py-2"
						>
							{{ __("No conversations with this agent yet.") }}
						</p>
					</div>
				</template>

				<template v-else>
					<div class="text-xs text-gray-500">{{ plain(picked.title) || picked.name }}</div>
					<p
						v-if="!messages.length && !loading"
						class="text-xs text-gray-500"
					>
						{{ __("This conversation has no messages.") }}
					</p>
					<div class="max-h-64 overflow-auto space-y-1.5">
						<div
							v-for="m in messages"
							:key="m.name"
							class="flex gap-2 items-start text-xs"
						>
							<span class="shrink-0 w-12 font-medium text-gray-500">{{ m.message_type === "User" ? __("User") : __("Agent") }}</span>
							<div class="flex-1 min-w-0 rounded px-2 py-1 bg-gray-50 text-gray-800 max-h-16 overflow-hidden whitespace-pre-wrap">{{ plain(m.text) }}</div>
							<div class="shrink-0 flex flex-col gap-1">
								<Button
									v-if="m.message_type === 'User'"
									size="sm"
									variant="solid"
									:label="__('Test from here')"
									@click="load(m, false)"
								/>
								<Button
									size="sm"
									variant="subtle"
									:label="__('Add as history')"
									@click="load(m, true)"
								/>
							</div>
						</div>
					</div>
				</template>
				<ErrorMessage :message="error" />
			</div>

			<div
				v-if="loaded.length"
				class="flex flex-wrap items-center gap-2 text-xs text-gray-600"
			>
				<span>{{ __("Loaded") }}:</span>
				<span
					v-for="(item, i) in loaded"
					:key="i"
					class="rounded-full bg-blue-50 text-blue-700 px-2 py-0.5"
				>{{ item }}</span>
				<Button
					size="sm"
					variant="ghost"
					:label="__('Clear')"
					@click="clearAll"
				/>
			</div>

			<EvalEarlierConversation :context="parsed" />

			<details>
				<summary class="text-xs text-gray-500 cursor-pointer">{{ __("Edit as JSON") }}</summary>
				<div class="mt-2 space-y-2">
					<Button
						v-if="!modelValue"
						size="sm"
						variant="subtle"
						:label="__('Insert example')"
						@click="$emit('update:modelValue', EXAMPLE_CONTEXT)"
					/>
					<FormControl
						type="textarea"
						:rows="8"
						:model-value="modelValue"
						@update:model-value="$emit('update:modelValue', $event)"
					/>
				</div>
			</details>
			<p
				class="text-xs"
				:class="validation ? 'text-red-600' : 'text-gray-500'"
			>
				{{ validation || __("Load one or more conversations, or edit the JSON directly.") }}
			</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { Button, ErrorMessage, FormControl } from "frappe-ui"
import { dayjs } from "@/dayjs"
import EvalEarlierConversation from "@/components/evals/EvalEarlierConversation.vue"
import { useCaseConversations } from "@/composables/useCaseConversations"
import { EXAMPLE_CONTEXT, mergeContexts, midConversationError, parseContext } from "@/utils/evalContext"

const props = defineProps({
	enabled: { type: Boolean, default: false },
	modelValue: { type: String, default: "" },
	suite: { type: String, required: true },
})
const emit = defineEmits(["update:enabled", "update:modelValue", "use-prompt"])

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s
const { conversations, messages, loading, error, search, open, contextUpTo } = useCaseConversations(props.suite)

const term = ref("")
const picked = ref(null)
const loaded = ref([])
let searchTimer = null

const parsed = computed(() => parseContext(props.modelValue))
const validation = computed(() => (props.enabled ? midConversationError(props.modelValue) : ""))

function toggle(value) {
	emit("update:enabled", value)
}

watch(
	() => props.enabled,
	(on) => {
		if (on && !conversations.value.length) search("")
	},
	{ immediate: true },
)

function onSearch(value) {
	term.value = value
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => search(value), 300)
}

async function pick(conversation) {
	picked.value = conversation
	await open(conversation.name)
}

async function load(message, includeMessage) {
	const context = await contextUpTo(picked.value.name, message.name, includeMessage)
	if (!context) return
	const { message_text: messageText, ...earlier } = context
	emit("update:modelValue", JSON.stringify(mergeContexts([parsed.value, earlier]), null, 2))
	loaded.value.push(plain(picked.value.title) || picked.value.name)
	if (!includeMessage) emit("use-prompt", plain(messageText))
	picked.value = null
}

function clearAll() {
	loaded.value = []
	emit("update:modelValue", "")
}

// Chat text is stored as HTML; the picker and the prompt want the words.
function plain(html) {
	const doc = new DOMParser().parseFromString(html || "", "text/html")
	return (doc.body.textContent || "").trim()
}
</script>
