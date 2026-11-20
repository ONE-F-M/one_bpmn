<template>
	<aside class="lsp-root">
		<div class="lsp-head">
			<div class="lsp-title">
				Security
				<small>{{ scriptLabel || "Unsaved script" }}</small>
			</div>
			<Badge :theme="headerTheme" size="sm">
				{{ headerStatus }}
			</Badge>
			<Button variant="ghost" icon="x" label="Close" @click="emit('close')" />
		</div>
		<p v-if="headerStatus === 'Rejected' && latestRequest?.decision_note" class="lsp-note">
			{{ latestRequest.decision_note }}
		</p>

		<div class="lsp-body">
			<div class="lsp-group-head">
				<span>Used, needs approval</span>
				<span>{{ needsApproval.length }}</span>
			</div>
			<div v-for="item in needsApproval" :key="`${item.name}-${item.line}`" class="lsp-item">
				<span class="lsp-check lsp-check--on" />
				<div class="lsp-label">
					{{ item.category }} <span class="lsp-mono">{{ item.name }}</span>
					<small>{{ itemNote(item) }}</small>
				</div>
			</div>
			<p v-if="!needsApproval.length" class="lsp-empty">
				Nothing in this script needs approval.
			</p>

			<div class="lsp-group-head">
				<span>Allowed for this script</span>
				<span>{{ allowedSummary }}</span>
			</div>
			<div v-for="row in allowedRows" :key="row.key" class="lsp-item">
				<span class="lsp-check lsp-check--on" />
				<div class="lsp-label">
					{{ row.label }}
					<small v-if="row.note">{{ row.note }}</small>
				</div>
			</div>

			<div class="lsp-group-head">
				<span>Other categories</span>
				<span>approval</span>
			</div>
			<div v-for="name in otherCategories" :key="name" class="lsp-item">
				<span class="lsp-check" />
				<div class="lsp-label">{{ name }}</div>
			</div>
		</div>

		<div v-if="!readonly" class="lsp-foot">
			<p v-if="error" class="lsp-error">
				{{ error }}
			</p>
			<template v-if="askingReason">
				<Textarea
					v-model="reason"
					placeholder="Why does this script need these items?"
					:rows="3"
				/>
				<div class="lsp-actions">
					<Button label="Cancel" @click="askingReason = false" />
					<Button
						variant="solid"
						label="Send request"
						:loading="requesting"
						:disabled="!reason.trim()"
						@click="send"
					/>
				</div>
			</template>
			<div v-else class="lsp-actions">
				<Button
					v-if="latestRequest"
					label="View request"
					:link="`/app/script-approval-request/${latestRequest.name}`"
				/>
				<Button
					variant="solid"
					label="Request approval"
					:disabled="Boolean(blockedReason)"
					@click="askingReason = true"
				/>
			</div>
			<small v-if="blockedReason && !askingReason" class="lsp-why">{{
				blockedReason
			}}</small>
		</div>
	</aside>
</template>

<script setup>
import { computed, ref } from "vue";
import { Badge, Button, Textarea } from "frappe-ui";

const props = defineProps({
	lint: { type: Object, default: null },
	scriptLabel: { type: String, default: "" },
	saved: { type: Boolean, default: false },
	dirty: { type: Boolean, default: false },
	readonly: { type: Boolean, default: false },
	requesting: { type: Boolean, default: false },
	error: { type: String, default: "" },
});
const emit = defineEmits(["close", "request"]);

const NOT_APPROVABLE = ["Syntax error", "Script import"];
const THEMES = { "Needs approval": "orange", Rejected: "red", Approved: "green", Clear: "green" };

const askingReason = ref(false);
const reason = ref("");

const findings = computed(() => props.lint?.findings || []);
const latestRequest = computed(() => props.lint?.latest_request || null);
const needsApproval = computed(() =>
	findings.value.filter((f) => !f.approved && !NOT_APPROVABLE.includes(f.category)),
);
const headerStatus = computed(() => {
	const latest = latestRequest.value;
	if (needsApproval.value.length && latest && latest.status !== "Approved") return latest.status;
	if (needsApproval.value.length) return "Needs approval";
	return findings.value.some((f) => f.approved) ? "Approved" : "Clear";
});
const headerTheme = computed(() => THEMES[headerStatus.value] || "blue");

const allowedCategories = computed(() =>
	(props.lint?.categories || []).filter(
		(c) => c.allowed_by_default && props.lint?.in_use?.[c.name],
	),
);
const approvedFindings = computed(() => findings.value.filter((f) => f.approved));
const allowedRows = computed(() => [
	...allowedCategories.value.map((c) => ({
		key: c.name,
		label: c.name,
		note: namesNote(props.lint.in_use[c.name]),
	})),
	...approvedFindings.value.map((f) => ({
		key: `ok-${f.name}`,
		label: f.category,
		note: `${f.name}, approved ${f.request}`,
	})),
]);
const allowedSummary = computed(
	() => `${allowedCategories.value.length} default, ${approvedFindings.value.length} approved`,
);
const otherCategories = computed(() =>
	(props.lint?.categories || [])
		.filter((c) => !c.allowed_by_default && !props.lint?.in_use?.[c.name])
		.map((c) => c.name),
);

const blockedReason = computed(() => {
	if (props.dirty || !props.saved)
		return "Save the script first: the request is made from the saved script.";
	if (!needsApproval.value.length) return "Nothing in this script needs approval.";
	if (props.lint?.open_request) return `Request ${props.lint.open_request} is already open.`;
	return "";
});

function namesNote(names) {
	return names.length > 2
		? `${names.slice(0, 2).join(", ")}, +${names.length - 2}`
		: names.join(", ");
}

function itemNote(item) {
	const where = item.library
		? `Line ${item.line}, through ${item.library}`
		: `Line ${item.line}`;
	return props.lint?.open_request
		? `${where}. ${props.lint.open_request} is open.`
		: `${where}.`;
}

function send() {
	emit("request", reason.value.trim());
	askingReason.value = false;
	reason.value = "";
}
</script>

<style scoped src="./LogixSecurityPanel.css"></style>
