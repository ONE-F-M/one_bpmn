<template>
	<div
		v-if="canManage && (primary || menuOptions.length)"
		class="flex items-center gap-2"
	>
		<Button
			v-if="primary"
			variant="solid"
			size="sm"
			:icon-left="primary.icon"
			:loading="busy === primary.method"
			@click="start(primary)"
		>
			{{ primary.label }}
		</Button>
		<Dropdown
			v-if="menuOptions.length"
			:options="menuOptions"
			placement="right"
		>
			<Button
				variant="subtle"
				size="sm"
				icon="more-horizontal"
				label="More actions"
			/>
		</Dropdown>

		<Dialog
			v-model="dialogOpen"
			:options="{ title: pending?.label, size: 'sm' }"
		>
			<template #body-content>
				<div class="space-y-3">
					<p class="text-sm text-gray-600">{{ pending?.description }}</p>
					<FormControl
						v-model="reason"
						type="textarea"
						label="Reason"
						placeholder="Why are you doing this? It is kept in the instance history."
						:rows="3"
					/>
					<ErrorMessage :message="dialogError" />
				</div>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button
						variant="ghost"
						@click="dialogOpen = false"
					>
						Keep as is
					</Button>
					<Button
						variant="solid"
						:theme="pending?.danger ? 'red' : 'gray'"
						:loading="busy === pending?.method"
						@click="confirm"
					>
						{{ pending?.label }}
					</Button>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { Button, Dialog, Dropdown, ErrorMessage, FormControl } from "frappe-ui"
import { useCurrentUser } from "@/composables/useCurrentUser"
import { useInstanceControl } from "@/composables/useInstanceControl"

const props = defineProps({
	details: { type: Object, required: true },
	// A parked AI step is retried from its own banner, so the generic retry stays out of the way.
	parkedAi: { type: Boolean, default: false },
})
const emit = defineEmits(["changed", "notice"])

const ACTIONS = [
	{ method: "retry_failed_step", label: "Retry failed step", icon: "rotate-ccw", when: ["Errored"], primary: true },
	{ method: "resume_instance", label: "Resume", icon: "play", when: ["Suspended"], primary: true },
	{
		method: "suspend_instance",
		label: "Suspend",
		icon: "pause",
		when: ["Active"],
		needsReason: true,
		description: "The instance stops here. Timers, messages and AI steps wait until you resume it.",
	},
	{
		method: "cancel_instance",
		label: "Cancel instance",
		icon: "x-circle",
		when: ["Queued", "Active", "Errored", "Suspended"],
		needsReason: true,
		danger: true,
		description: "This ends the instance for good, and every task still waiting on it is cancelled. It cannot be undone.",
	},
]

const { currentRoles } = useCurrentUser()
const { busy, runControl } = useInstanceControl()

const canManage = computed(() => currentRoles.value.some((r) => r === "System Manager" || r === "Process Owner"))
const available = computed(() => ACTIONS.filter((a) => a.when.includes(props.details.status)))
const primary = computed(() =>
	available.value.find((a) => a.primary && !(props.parkedAi && a.method === "retry_failed_step"))
)
const menuOptions = computed(() =>
	available.value
		.filter((a) => !a.primary)
		.map((a) => ({ label: a.label, icon: a.icon, onClick: () => start(a) }))
)

const dialogOpen = ref(false)
const pending = ref(null)
const reason = ref("")
const dialogError = ref("")

function start(action) {
	if (!action.needsReason) {
		run(action, "")
		return
	}
	pending.value = action
	reason.value = ""
	dialogError.value = ""
	dialogOpen.value = true
}

async function confirm() {
	if (!reason.value.trim()) {
		dialogError.value = "A reason is required."
		return
	}
	try {
		await run(pending.value, reason.value.trim(), true)
		dialogOpen.value = false
	} catch (e) {
		dialogError.value = e.message
	}
}

async function run(action, why, fromDialog = false) {
	try {
		await runControl(action.method, props.details.name, why)
		emit("changed")
	} catch (e) {
		if (fromDialog) throw e
		// A retry whose step fails again is refused, and the instance stays Errored under a new reference.
		const retried = action.method === "retry_failed_step"
		emit("notice", retried ? `The step failed again. Fix its cause, then retry. ${e.message}` : e.message)
		if (retried) emit("changed")
	}
}
</script>
