<template>
	<div v-if="canRedelegate" class="rounded-lg border border-gray-200 px-4 py-3">
		<div v-if="!redelegateWarning" class="flex items-center justify-between gap-3">
			<div class="text-gray-600 text-xs">
				This delegation stopped. Handing it back runs the worker again against the limits
				as they stand now.
			</div>
			<Button variant="subtle" :loading="redelegateBusy" @click="askRedelegate()">
				Hand back to the agent
			</Button>
		</div>
		<div v-else class="flex flex-col gap-2">
			<div
				class="rounded-md bg-orange-50 border border-orange-200 px-3 py-2 text-orange-900"
			>
				{{ redelegateWarning }}
			</div>
			<div class="flex gap-2 justify-end">
				<Button variant="ghost" @click="redelegateWarning = ''">Leave it stopped</Button>
				<Button variant="solid" :loading="redelegateBusy" @click="askRedelegate(true)">
					Hand it back anyway
				</Button>
			</div>
		</div>
	</div>

	<div
		v-if="redelegateOutcome"
		class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-xs"
	>
		<div class="font-medium text-gray-900">
			Handed back — attempt {{ redelegateOutcome.attempt }}, the
			{{ ordinal(redelegateOutcome.by_a_person) }}
			a person has asked for.
		</div>
		<div class="text-gray-600 mt-0.5">
			It has {{ redelegateOutcome.deadline_minutes }} minute(s) this time — a hand-over
			starts the clock again, unlike an automatic retry.
			<span v-if="redelegateOutcome.previous_run_retired">
				The previous run was closed first.
			</span>
			<span v-if="redelegateOutcome.state !== 'started'">
				The worker did not start — check the Error Log.
			</span>
		</div>
	</div>

	<div v-if="canCancel" class="rounded-lg border border-gray-200 px-4 py-3">
		<div v-if="!cancelling" class="flex items-center justify-between gap-3">
			<div class="text-gray-600 text-xs">
				This delegation is still running. Stopping it closes the hand-off and wakes whoever
				is waiting on it.
			</div>
			<Button variant="subtle" theme="red" @click="cancelling = true">
				Cancel delegation
			</Button>
		</div>
		<div v-else class="flex flex-col gap-2">
			<FormControl
				v-model="cancelReason"
				type="text"
				label="Why (optional)"
				placeholder="Kept retrying the same broken endpoint"
			/>
			<div class="text-xs text-gray-500">
				The worker stops advancing, but a pass already running cannot be interrupted — you
				will be told which happened.
			</div>
			<div class="flex gap-2 justify-end">
				<Button variant="ghost" @click="cancelling = false">Keep it running</Button>
				<Button variant="solid" theme="red" :loading="cancelBusy" @click="confirmCancel">
					Stop this delegation
				</Button>
			</div>
		</div>
	</div>

	<div
		v-if="cancelOutcome"
		class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-xs"
	>
		<div class="font-medium text-gray-900">{{ cancelOutcome.detail }}</div>
		<div class="text-gray-600 mt-0.5">
			<span v-if="cancelOutcome.worker_stopped">
				The worker will not advance any further. A pass already running when you cancelled
				may still finish — nothing can interrupt one mid-flight.
			</span>
			<span v-else>
				The worker had no running process to stop, so the delegation simply stopped
				waiting.
			</span>
			<span v-if="cancelOutcome.caller_woken"> The agent waiting on it was woken.</span>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from "vue";
import { Button, FormControl, frappeRequest } from "frappe-ui";
import { A2A_API } from "@/utils/a2aApi";
import { ordinal } from "@/utils/a2aFormat";

// A delegation that has not finished can be stopped; only one that stopped can be handed back.
const CANCELLABLE = ["Delegated", "In Progress", "Needs Review"];
const REDELEGATABLE = ["Failed", "Needs Review", "Cancelled"];

const props = defineProps({
	row: { type: Object, required: true },
});
const emit = defineEmits(["changed", "error"]);

const cancelling = ref(false);
const cancelReason = ref("");
const cancelOutcome = ref(null);
const redelegateWarning = ref("");
const redelegateOutcome = ref(null);
const cancelBusy = ref(false);
const redelegateBusy = ref(false);

const canRedelegate = computed(() => REDELEGATABLE.includes(props.row.status));
const canCancel = computed(() => CANCELLABLE.includes(props.row.status));

async function confirmCancel() {
	cancelBusy.value = true;
	try {
		cancelOutcome.value = await frappeRequest({
			url: A2A_API + "cancel_delegation",
			params: { name: props.row.name, reason: cancelReason.value || undefined },
		});
		cancelling.value = false;
		cancelReason.value = "";
		emit("changed", "Cancelled");
	} catch (e) {
		emit("error", e.message || String(e));
		cancelling.value = false;
	} finally {
		cancelBusy.value = false;
	}
}

async function askRedelegate(acknowledged = false) {
	redelegateBusy.value = true;
	try {
		const result = await frappeRequest({
			url: A2A_API + "redelegate_delegation",
			params: { name: props.row.name, acknowledged: acknowledged ? 1 : 0 },
		});
		if (result.state === "confirm") {
			redelegateWarning.value = result.warning;
			return;
		}
		redelegateWarning.value = "";
		redelegateOutcome.value = result;
		emit("changed", "In Progress");
	} catch (e) {
		emit("error", e.message || String(e));
		redelegateWarning.value = "";
	} finally {
		redelegateBusy.value = false;
	}
}
</script>
