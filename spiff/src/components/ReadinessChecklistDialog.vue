<template>
	<Dialog v-model="showDialog" :options="{ title: dialogTitle, size: '5xl' }">
		<template #body-content>
			<!-- Loading state -->
			<div v-if="loading" class="flex flex-col items-center justify-center py-12">
				<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-3"></div>
				<span class="text-sm text-gray-500">Checking prerequisites…</span>
			</div>

			<!-- Checklist content -->
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

				<!-- Empty state (no references in BPMN) -->
				<div v-if="!checklist?.categories?.length && !loading" class="text-center py-8 text-gray-400">
					<Icon icon="lucide:file-check" class="w-10 h-10 mx-auto mb-2 opacity-50" />
					<p class="text-sm">No external references found in this BPMN diagram.</p>
				</div>

				<!-- Category sections — 2-column masonry layout -->
				<div class="columns-2 gap-3 max-h-[60vh] overflow-y-auto pr-1">
					<div
						v-for="category in checklist?.categories || []"
						:key="category.label"
						class="border border-gray-200 rounded-lg overflow-hidden mb-3 break-inside-avoid"
					>
						<!-- Category header -->
						<div class="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
							<Icon :icon="'lucide:' + category.icon" class="w-4 h-4 text-gray-500" />
							<span class="text-sm font-semibold text-gray-700">{{ category.label }}</span>
							<span class="ml-auto text-xs text-gray-400">
								{{ categoryStatus(category) }}
							</span>
						</div>

						<!-- Items -->
						<div class="divide-y divide-gray-100">
							<div
								v-for="item in category.items"
								:key="item.name"
								class="flex items-center gap-2 px-3 py-1.5 transition-colors"
								:class="itemRowClass(item)"
							>
								<!-- Status icon -->
								<Icon
									:icon="itemIcon(item)"
									class="w-4 h-4 shrink-0"
									:class="itemIconClass(item)"
								/>
								<!-- Label -->
								<span class="text-sm text-gray-800 flex-1 truncate" :title="item.name">{{ item.name }}</span>
								<!-- Detail for warnings -->
								<span
									v-if="item.detail"
									class="text-xs text-amber-700 max-w-[180px] truncate"
									:title="item.detail"
								>
									{{ item.detail }}
								</span>
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
					<template v-if="checklist && !loading">
						<span v-if="checklist.total_missing > 0" class="text-red-600 font-medium">
							{{ checklist.total_missing }} missing
						</span>
						<span v-if="checklist.total_missing > 0 && checklist.total_warnings > 0"> · </span>
						<span v-if="checklist.total_warnings > 0" class="text-amber-600 font-medium">
							{{ checklist.total_warnings }} {{ checklist.total_warnings === 1 ? 'warning' : 'warnings' }}
						</span>
						<span v-if="checklist.total_missing === 0 && checklist.total_warnings === 0" class="text-green-600 font-medium">
							All {{ checklist.total_checked }} checks passed
						</span>
					</template>
				</div>
				<!-- Right: action buttons -->
				<div class="flex gap-2">
					<Button
						v-if="mode === 'deploy'"
						variant="subtle"
						@click="$emit('cancel')"
					>Cancel</Button>
					<Button
						v-if="mode === 'deploy'"
						variant="solid"
						@click="$emit('deploy')"
						:disabled="!checklist?.all_ready || loading"
					>Deploy</Button>
					<Button
						v-if="mode === 'import'"
						variant="solid"
						@click="$emit('close')"
					>OK</Button>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed } from "vue";
import { Dialog, Button } from "frappe-ui";
import { Icon } from "@iconify/vue";

const props = defineProps({
	checklist: {
		type: Object,
		default: null,
	},
	mode: {
		type: String,
		default: "import", // "import" or "deploy"
		validator: (v) => ["import", "deploy"].includes(v),
	},
	loading: {
		type: Boolean,
		default: false,
	},
});

const showDialog = defineModel({ type: Boolean, default: false });

defineEmits(["close", "cancel", "deploy"]);

const dialogTitle = computed(() =>
	props.mode === "deploy" ? "Deploy Readiness" : "Import Readiness"
);

// ── Summary banner ──────────────────────────────────────────────────────

const summaryClass = computed(() => {
	if (props.loading) return "bg-blue-50 border-blue-200 text-blue-800";
	if (!props.checklist) return "bg-gray-50 border-gray-200 text-gray-600";
	if (props.checklist.total_missing > 0) return "bg-red-50 border-red-200 text-red-800";
	if (props.checklist.total_warnings > 0) return "bg-amber-50 border-amber-200 text-amber-800";
	return "bg-green-50 border-green-200 text-green-800";
});

const summaryIcon = computed(() => {
	if (props.loading) return "lucide:loader-2";
	if (!props.checklist) return "lucide:info";
	if (props.checklist.total_missing > 0) return "lucide:alert-circle";
	if (props.checklist.total_warnings > 0) return "lucide:alert-triangle";
	return "lucide:check-circle-2";
});

const summaryTitle = computed(() => {
	if (props.loading) return "Checking…";
	if (!props.checklist) return "No data";
	if (props.checklist.total_missing > 0) return "Missing Prerequisites";
	if (props.checklist.total_warnings > 0) return "Ready with Warnings";
	return "All Checks Passed";
});

const summaryDetail = computed(() => {
	if (props.loading) return "Validating BPMN prerequisites against the database…";
	if (!props.checklist) return "";
	const c = props.checklist;
	if (c.total_missing > 0) {
		const parts = [`${c.total_missing} item${c.total_missing > 1 ? "s" : ""} missing`];
		if (c.total_warnings > 0) parts.push(`${c.total_warnings} warning${c.total_warnings > 1 ? "s" : ""}`);
		if (props.mode === "deploy") parts.push("— resolve before deploying");
		return parts.join(" · ");
	}
	if (c.total_warnings > 0) {
		return `${c.total_warnings} potential conflict${c.total_warnings > 1 ? "s" : ""} detected — review recommended`;
	}
	return `${c.total_checked} prerequisite${c.total_checked > 1 ? "s" : ""} verified`;
});

// ── Item helpers ────────────────────────────────────────────────────────

function itemIcon(item) {
	if (item.type === "warning") return "lucide:alert-triangle";
	return item.exists ? "lucide:check-circle-2" : "lucide:x-circle";
}

function itemIconClass(item) {
	if (item.type === "warning") return "text-amber-500";
	return item.exists ? "text-green-500" : "text-red-500";
}

function itemRowClass(item) {
	if (item.type === "warning") return "bg-amber-50/50";
	if (!item.exists) return "bg-red-50/50";
	return "";
}

function categoryStatus(category) {
	const total = category.items.length;
	const warnings = category.items.filter((i) => i.type === "warning").length;
	const missing = category.items.filter((i) => i.type === "check" && !i.exists).length;
	const passed = total - warnings - missing;

	if (warnings > 0 && missing === 0) return `${warnings} warning${warnings > 1 ? "s" : ""}`;
	if (missing > 0) return `${missing} missing`;
	return `${passed}/${passed} passed`;
}
</script>
