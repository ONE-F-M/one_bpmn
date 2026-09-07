<template>
	<div class="border rounded-lg divide-y max-h-56 overflow-auto">
		<label
			v-for="a in agents"
			:key="a.name"
			class="flex items-start gap-2 px-3 py-2 cursor-pointer hover:bg-gray-50"
		>
			<input
				type="checkbox"
				class="mt-1"
				:checked="modelValue.includes(a.name)"
				@change="toggle(a.name)"
			/>
			<span>
				<span class="text-sm text-gray-900">{{ a.agent_name }}</span>
				<span class="block text-xs text-gray-500">{{ a.agent_id }}</span>
			</span>
		</label>
		<p v-if="!agents.length" class="px-3 py-3 text-sm text-gray-500">
			No agents are exposed yet, so there is nothing to grant. Tick “Exposed over A2A” on an
			enabled, Live agent first.
		</p>
	</div>
</template>

<script setup>
// WI-001934: granting a caller access is a list of agents, and the only agents
// that can be granted are the exposed ones — so the picker is fed from the same
// catalogue the Our-agents tab shows rather than every agent on the site.
const props = defineProps({
	modelValue: { type: Array, default: () => [] },
	agents: { type: Array, default: () => [] },
})
const emit = defineEmits(["update:modelValue"])

function toggle(name) {
	const next = props.modelValue.includes(name)
		? props.modelValue.filter((n) => n !== name)
		: [...props.modelValue, name]
	emit("update:modelValue", next)
}
</script>
