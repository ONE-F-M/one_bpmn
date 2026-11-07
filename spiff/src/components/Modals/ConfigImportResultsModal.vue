<template>
	<Dialog v-model="showDialog" :options="{ title: dialogTitle, size: '5xl' }">
		<template #body-content>
			<!-- Loading state -->
			<div v-if="importing" class="flex flex-col items-center justify-center py-12">
				<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-3"></div>
				<span class="text-sm text-gray-500">Importing configuration…</span>
			</div>

			<!-- Results -->
			<div v-else class="space-y-4">
				<!-- Summary banner -->
				<div
					class="flex items-center gap-3 rounded-lg px-4 py-3 text-sm border"
					:class="summaryClass"
				>
					<Icon :icon="summaryIcon" class="w-5 h-5 shrink-0" />
					<div class="flex-1">
						<div class="font-semibold">{{ summaryTitle }}</div>
						<div class="mt-0.5 opacity-90">{{ summaryDetail }}</div>
					</div>
				</div>

				<!-- Created items -->
				<div v-if="results.created?.length" class="space-y-1">
					<div class="text-xs font-semibold text-green-700 uppercase tracking-wider px-1">
						Created ({{ results.created.length }})
					</div>
					<div class="border border-green-200 rounded-lg divide-y divide-green-100">
						<div
							v-for="item in results.created"
							:key="item.name + item.type"
							class="flex items-center gap-2 px-3 py-2 bg-green-50/50"
						>
							<Icon icon="lucide:check-circle-2" class="w-4 h-4 text-green-500 shrink-0" />
							<span class="text-sm text-gray-800 flex-1">{{ item.name }}</span>
							<span class="text-xs text-gray-400">{{ item.type }}</span>
						</div>
					</div>
				</div>

				<!-- Skipped items -->
				<div v-if="results.skipped?.length" class="space-y-1">
					<div class="text-xs font-semibold text-gray-500 uppercase tracking-wider px-1">
						Skipped — Already Exist ({{ results.skipped.length }})
					</div>
					<div class="border border-gray-200 rounded-lg divide-y divide-gray-100">
						<div
							v-for="item in results.skipped"
							:key="item.name + item.type"
							class="flex items-center gap-2 px-3 py-2"
						>
							<Icon icon="lucide:skip-forward" class="w-4 h-4 text-gray-400 shrink-0" />
							<span class="text-sm text-gray-600 flex-1">{{ item.name }}</span>
							<span class="text-xs text-gray-400">{{ item.type }}</span>
						</div>
					</div>
				</div>

				<!-- Needs confirmation (modified Server Scripts) -->
				<div v-if="results.needs_confirmation?.length" class="space-y-1">
					<div class="text-xs font-semibold text-amber-700 uppercase tracking-wider px-1">
						Modified — Review Required ({{ results.needs_confirmation.length }})
					</div>
					<div class="border border-amber-200 rounded-lg divide-y divide-amber-100">
						<div
							v-for="(item, idx) in results.needs_confirmation"
							:key="item.name"
							class="bg-amber-50/50"
						>
							<!-- Header row -->
							<div class="flex items-center gap-2 px-3 py-2">
								<Icon icon="lucide:alert-triangle" class="w-4 h-4 text-amber-500 shrink-0" />
								<span class="text-sm font-medium text-gray-800 flex-1">{{ item.name }}</span>
								<span class="text-xs text-gray-400 mr-2">{{ item.type }}</span>
								<button
									@click="toggleDiff(idx)"
									class="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
								>
									<Icon :icon="expandedDiffs[idx] ? 'lucide:chevron-up' : 'lucide:chevron-down'" class="w-3 h-3" />
									{{ expandedDiffs[idx] ? "Hide" : "View" }} Diff
								</button>
								<button
									v-if="!overwriteDecisions[idx]"
									@click="overwriteDecisions[idx] = 'overwrite'"
									class="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700 transition-colors"
								>Overwrite</button>
								<button
									v-if="!overwriteDecisions[idx]"
									@click="overwriteDecisions[idx] = 'skip'"
									class="text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded hover:bg-gray-300 transition-colors"
								>Skip</button>
								<span
									v-if="overwriteDecisions[idx] === 'overwrite'"
									class="text-xs text-blue-600 font-medium flex items-center gap-1"
								>
									<Icon icon="lucide:check" class="w-3 h-3" /> Will Overwrite
									<button @click="overwriteDecisions[idx] = null" class="text-gray-400 hover:text-gray-600 ml-1">
										<Icon icon="lucide:x" class="w-3 h-3" />
									</button>
								</span>
								<span
									v-if="overwriteDecisions[idx] === 'skip'"
									class="text-xs text-gray-500 font-medium flex items-center gap-1"
								>
									<Icon icon="lucide:skip-forward" class="w-3 h-3" /> Will Skip
									<button @click="overwriteDecisions[idx] = null" class="text-gray-400 hover:text-gray-600 ml-1">
										<Icon icon="lucide:x" class="w-3 h-3" />
									</button>
								</span>
							</div>

							<!-- Diff view -->
							<div v-if="expandedDiffs[idx]" class="px-3 pb-3">
								<div class="grid grid-cols-2 gap-2 text-xs">
									<div>
										<div class="font-semibold text-red-700 mb-1 flex items-center gap-1">
											<Icon icon="lucide:server" class="w-3 h-3" /> Existing (Production)
										</div>
										<pre class="bg-red-50 border border-red-200 rounded p-2 font-mono text-[11px] text-red-900 overflow-x-auto max-h-64 whitespace-pre-wrap">{{ item.existing_script }}</pre>
									</div>
									<div>
										<div class="font-semibold text-green-700 mb-1 flex items-center gap-1">
											<Icon icon="lucide:download" class="w-3 h-3" /> Incoming (Config File)
										</div>
										<pre class="bg-green-50 border border-green-200 rounded p-2 font-mono text-[11px] text-green-900 overflow-x-auto max-h-64 whitespace-pre-wrap">{{ item.incoming_script }}</pre>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex items-center justify-between w-full">
				<!-- Left: summary counts -->
				<div class="text-sm text-gray-500">
					<template v-if="!importing && results">
						<span v-if="results.created?.length" class="text-green-600 font-medium">
							{{ results.created.length }} created
						</span>
						<span v-if="results.created?.length && results.skipped?.length"> · </span>
						<span v-if="results.skipped?.length" class="text-gray-500">
							{{ results.skipped.length }} skipped
						</span>
						<span v-if="(results.created?.length || results.skipped?.length) && results.needs_confirmation?.length"> · </span>
						<span v-if="results.needs_confirmation?.length" class="text-amber-600 font-medium">
							{{ results.needs_confirmation.length }} to review
						</span>
					</template>
				</div>

				<!-- Right: action buttons -->
				<div class="flex gap-2">
					<Button
						v-if="hasUndecided"
						variant="subtle"
						@click="overwriteAll"
					>Overwrite All</Button>
					<Button
						v-if="results.needs_confirmation?.length && !allDecided"
						variant="subtle"
						@click="skipAll"
					>Skip All</Button>
					<Button
						variant="solid"
						@click="applyDecisions"
						:loading="applying"
						:disabled="!allDecided && results.needs_confirmation?.length > 0"
					>
						{{ results.needs_confirmation?.length ? "Apply & Close" : "Close" }}
					</Button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { Dialog, Button, frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";

const props = defineProps({
	results: {
		type: Object,
		default: () => ({ created: [], skipped: [], needs_confirmation: [] }),
	},
	importing: {
		type: Boolean,
		default: false,
	},
});

const showDialog = defineModel({ type: Boolean, default: false });
const emit = defineEmits(["done"]);

const expandedDiffs = ref({});
const overwriteDecisions = ref({});
const applying = ref(false);

// Reset state when dialog opens
watch(showDialog, (open) => {
	if (open) {
		expandedDiffs.value = {};
		overwriteDecisions.value = {};
		applying.value = false;
	}
});

const dialogTitle = computed(() => {
	if (props.importing) return "Importing Configuration…";
	return "Configuration Import Results";
});

// ── Summary banner ──────────────────────────────────────────────────────
const summaryClass = computed(() => {
	if (props.importing) return "bg-blue-50 border-blue-200 text-blue-800";
	const r = props.results;
	if (r.needs_confirmation?.length > 0) return "bg-amber-50 border-amber-200 text-amber-800";
	if (r.created?.length > 0) return "bg-green-50 border-green-200 text-green-800";
	return "bg-gray-50 border-gray-200 text-gray-600";
});

const summaryIcon = computed(() => {
	if (props.importing) return "lucide:loader-2";
	const r = props.results;
	if (r.needs_confirmation?.length > 0) return "lucide:alert-triangle";
	if (r.created?.length > 0) return "lucide:check-circle-2";
	return "lucide:check-circle-2";
});

const summaryTitle = computed(() => {
	if (props.importing) return "Importing…";
	const r = props.results;
	if (r.needs_confirmation?.length > 0) return "Review Required";
	if (r.created?.length > 0) return "Import Successful";
	return "All Records Already Exist";
});

const summaryDetail = computed(() => {
	if (props.importing) return "Processing configuration records…";
	const r = props.results;
	const parts = [];
	if (r.created?.length) parts.push(`${r.created.length} created`);
	if (r.skipped?.length) parts.push(`${r.skipped.length} already exist`);
	if (r.needs_confirmation?.length) parts.push(`${r.needs_confirmation.length} modified script(s) need your review`);
	return parts.join(" · ") || "No records to import";
});

// ── Decision helpers ────────────────────────────────────────────────────

const hasUndecided = computed(() => {
	const items = props.results.needs_confirmation || [];
	return items.some((_, idx) => !overwriteDecisions.value[idx]);
});

const allDecided = computed(() => {
	const items = props.results.needs_confirmation || [];
	if (items.length === 0) return true;
	return items.every((_, idx) => overwriteDecisions.value[idx]);
});

function toggleDiff(idx) {
	expandedDiffs.value[idx] = !expandedDiffs.value[idx];
}

function overwriteAll() {
	const items = props.results.needs_confirmation || [];
	for (let i = 0; i < items.length; i++) {
		overwriteDecisions.value[i] = "overwrite";
	}
}

function skipAll() {
	const items = props.results.needs_confirmation || [];
	for (let i = 0; i < items.length; i++) {
		if (!overwriteDecisions.value[i]) {
			overwriteDecisions.value[i] = "skip";
		}
	}
}

async function applyDecisions() {
	const items = props.results.needs_confirmation || [];
	const toOverwrite = [];

	for (let i = 0; i < items.length; i++) {
		if (overwriteDecisions.value[i] === "overwrite") {
			toOverwrite.push({
				name: items[i].name,
				script: items[i].incoming_script,
			});
		}
	}

	if (toOverwrite.length > 0) {
		applying.value = true;
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.config_export_import.confirm_overwrite_scripts",
				method: "POST",
				params: { overwrites: JSON.stringify(toOverwrite) },
			});
		} catch (err) {
			console.error("Failed to overwrite scripts:", err);
		} finally {
			applying.value = false;
		}
	}

	showDialog.value = false;
	emit("done");
}
</script>
