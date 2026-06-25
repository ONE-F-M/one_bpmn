<template>
	<!-- Google-Docs-style version history side panel -->
	<aside class="flex flex-col h-full w-80 shrink-0 bg-gray-50 border-l border-gray-200">
		<!-- Header -->
		<div class="flex items-center justify-between px-4 py-3 border-b border-gray-200">
			<h2 class="text-base font-medium text-gray-900">Version history</h2>
			<button
				class="w-7 h-7 flex items-center justify-center rounded hover:bg-gray-200 text-gray-500"
				title="Close"
				@click="$emit('close')"
			>
				<Icon icon="lucide:x" class="w-4 h-4" />
			</button>
		</div>

		<!-- Filter -->
		<div class="px-4 py-3">
			<select
				v-model="filter"
				class="w-full text-sm border border-gray-300 rounded-md px-3 py-2 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
			>
				<option value="all">All versions</option>
				<option value="named">Named versions</option>
			</select>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-y-auto px-2 pb-2">
			<!-- Loading -->
			<div v-if="loading" class="p-8 text-center text-gray-400">
				<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>
				Loading history…
			</div>

			<!-- Empty -->
			<div v-else-if="visibleGroups.length === 0" class="p-8 text-center text-gray-400">
				<Icon icon="lucide:history" class="w-10 h-10 mx-auto mb-2 opacity-50" />
				<p class="text-sm">{{ filter === 'named' ? 'No named versions yet.' : 'No saved versions yet.' }}</p>
			</div>

			<!-- Grouped history -->
			<template v-else>
				<div v-for="section in dateSections" :key="section.label" class="mb-2">
					<div class="px-2 pt-2 pb-1 text-xs font-medium text-gray-500">{{ section.label }}</div>

					<div
						v-for="group in section.groups"
						:key="group.key"
						class="rounded-lg mb-1"
						:class="group.is_current ? 'bg-white shadow-sm border border-gray-200' : ''"
					>
						<!-- Group header -->
						<div
							class="group flex items-start gap-1 px-2 py-2 rounded-lg cursor-pointer hover:bg-gray-100"
							:class="selectedVersion === group.head ? 'bg-blue-50' : ''"
							@click="onVersionClick(group.head)"
						>
							<button
								v-if="group.entries.length > 1"
								class="mt-0.5 text-gray-500 hover:text-gray-700"
								@click.stop="toggleExpand(group.key)"
							>
								<Icon
									:icon="expanded[group.key] ? 'lucide:chevron-down' : 'lucide:chevron-right'"
									class="w-4 h-4"
								/>
							</button>
							<span v-else class="w-4"></span>

							<div class="flex-1 min-w-0">
								<div class="text-sm font-medium text-gray-900 truncate">
									{{ group.is_named ? group.version_name : formatTime(group.timestamp) }}
								</div>
								<div v-if="group.is_named" class="text-xs text-blue-600">
									{{ formatTime(group.timestamp) }}
								</div>
								<div v-else-if="group.is_current" class="text-xs text-gray-500">Current version</div>
								<div class="flex items-center gap-1.5 mt-1">
									<span class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></span>
									<span class="text-xs text-gray-600 truncate">{{ group.author }}</span>
								</div>
							</div>

							<!-- Per-version menu -->
							<div class="relative">
								<button
									class="w-6 h-6 flex items-center justify-center rounded hover:bg-gray-200 text-gray-500 opacity-0 group-hover:opacity-100"
									:class="openMenu === group.head ? 'opacity-100 bg-gray-200' : ''"
									@click.stop="toggleMenu(group.head)"
								>
									<Icon icon="lucide:more-vertical" class="w-4 h-4" />
								</button>
								<div
									v-if="openMenu === group.head"
									class="absolute right-0 top-7 z-20 w-44 bg-white border border-gray-200 rounded-md shadow-lg py-1 text-sm"
								>
									<button class="w-full text-left px-3 py-2 hover:bg-gray-50 flex items-center gap-2" @click.stop="openNameDialog(group)">
										<Icon icon="lucide:pencil" class="w-4 h-4 text-gray-500" />
										{{ group.is_named ? 'Rename version' : 'Name this version' }}
									</button>
									<button class="w-full text-left px-3 py-2 hover:bg-gray-50 flex items-center gap-2" @click.stop="compareVersion(group.head)">
										<Icon icon="lucide:git-compare" class="w-4 h-4 text-gray-500" />
										Compare with current
									</button>
									<button
										v-if="!group.is_current"
										class="w-full text-left px-3 py-2 hover:bg-gray-50 flex items-center gap-2"
										@click.stop="restoreVersion(group.head)"
									>
										<Icon icon="lucide:rotate-ccw" class="w-4 h-4 text-gray-500" />
										Restore this version
									</button>
								</div>
							</div>
						</div>

						<!-- Expanded sub-entries -->
						<div v-if="expanded[group.key] && group.entries.length > 1" class="pb-1">
							<div
								v-for="entry in group.entries"
								:key="entry.name"
								class="flex items-start gap-1 pl-9 pr-2 py-1.5 rounded-lg cursor-pointer hover:bg-gray-100"
								:class="selectedVersion === entry.name ? 'bg-blue-50' : ''"
								@click="onVersionClick(entry.name)"
							>
								<div class="flex-1 min-w-0">
									<div class="text-sm text-gray-800">{{ formatTime(entry.timestamp) }}</div>
									<div class="flex items-center gap-1.5 mt-0.5">
										<span class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></span>
										<span class="text-xs text-gray-600 truncate">{{ entry.author }}</span>
									</div>
								</div>
								<button
									class="w-6 h-6 flex items-center justify-center rounded hover:bg-gray-200 text-gray-500"
									@click.stop="compareVersion(entry.name)"
									title="Compare with current"
								>
									<Icon icon="lucide:git-compare" class="w-4 h-4" />
								</button>
							</div>
						</div>
					</div>
				</div>
			</template>
		</div>

		<!-- Footer -->
		<div class="border-t border-gray-200 px-4 py-3 space-y-2">
			<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
				<input type="checkbox" v-model="highlightChanges" class="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
				Highlight changes
			</label>
			<button
				class="text-xs text-blue-600 hover:text-blue-700 hover:underline"
				@click="$emit('compare-deployed')"
			>
				Compare deployed versions…
			</button>
		</div>
	</aside>

	<!-- Name / rename dialog -->
	<Dialog v-model="showNameDialog" :options="{ title: nameDialogTitle, size: 'sm' }">
		<template #body-content>
			<FormControl
				type="text"
				v-model="nameInput"
				label="Version name"
				placeholder="e.g. Final draft"
				@keydown.enter="submitName"
			/>
		</template>
		<template #actions>
			<div class="flex gap-2 justify-end">
				<Button variant="subtle" @click="showNameDialog = false">Cancel</Button>
				<Button variant="solid" :loading="savingName" @click="submitName">Save</Button>
			</div>
		</template>
	</Dialog>

	<!-- Diff viewer dialog -->
	<Dialog v-model="showDiffDialog" :options="{ title: 'Diagram Comparison', size: '7xl' }">
		<template #body-content>
			<div class="h-[70vh]">
				<DiffViewer
					v-if="diffOldXml && diffNewXml"
					:key="diffKey"
					:oldXml="diffOldXml"
					:newXml="diffNewXml"
					:oldLabel="diffOldLabel"
					:newLabel="diffNewLabel"
					:highlightChanges="highlightChanges"
				/>
			</div>
		</template>
		<template #actions>
			<Button variant="subtle" @click="showDiffDialog = false">Close</Button>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import { dayjs } from "@/dayjs";
import DiffViewer from "@/components/DiffViewer.vue";

const props = defineProps({
	/** BPMN Process Model document name (activeDiagramName) */
	modelName: { type: String, default: null },
	/** async fn returning the current canvas XML */
	getCurrentXml: { type: Function, default: null },
});

const emit = defineEmits(["error", "restored", "close", "compare-deployed"]);

const loading = ref(false);
const groups = ref([]);
const filter = ref("all");
const expanded = ref({});
const openMenu = ref(null);
const selectedVersion = ref(null);
const highlightChanges = ref(true);

// ── Diff state ──
const showDiffDialog = ref(false);
const diffOldXml = ref("");
const diffNewXml = ref("");
const diffOldLabel = ref("");
const diffNewLabel = ref("");
const diffKey = ref(0);

// ── Name dialog state ──
const showNameDialog = ref(false);
const nameInput = ref("");
const savingName = ref(false);
const nameTarget = ref(null);
const nameDialogTitle = computed(() => (nameTarget.value?.is_named ? "Rename version" : "Name this version"));

const visibleGroups = computed(() => {
	if (filter.value === "named") return groups.value.filter((g) => g.is_named);
	return groups.value;
});

// Group the version groups under date-section headers (Today / date).
const dateSections = computed(() => {
	const sections = [];
	let current = null;
	for (const g of visibleGroups.value) {
		const label = dateLabel(g.timestamp);
		if (!current || current.label !== label) {
			current = { label, groups: [] };
			sections.push(current);
		}
		current.groups.push(g);
	}
	return sections;
});

async function load() {
	if (!props.modelName) return;
	loading.value = true;
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_edit_history",
			params: { model_name: props.modelName },
		});
		groups.value = res.message || res || [];
		// Auto-expand the current (top) group so recent edits are visible.
		if (groups.value.length) expanded.value[groups.value[0].key] = true;
	} catch (error) {
		console.error("Failed to load version history:", error);
		groups.value = [];
		emit("error", { title: "Error", message: "Failed to load version history.", theme: "red" });
	} finally {
		loading.value = false;
	}
}

function toggleExpand(key) {
	expanded.value[key] = !expanded.value[key];
}

function toggleMenu(name) {
	openMenu.value = openMenu.value === name ? null : name;
}

function onVersionClick(name) {
	selectedVersion.value = name;
	compareVersion(name);
}

async function fetchSnapshotXml(versionName) {
	const res = await frappeRequest({
		url: "/api/method/one_bpmn.api.version_history.get_snapshot_xml",
		params: { version_name: versionName },
	});
	return res.message || res;
}

async function compareVersion(versionName) {
	openMenu.value = null;
	try {
		const snap = await fetchSnapshotXml(versionName);
		if (!snap.xml_content) {
			emit("error", { title: "Error", message: "Could not retrieve this version's XML.", theme: "red" });
			return;
		}
		let currentXml = props.getCurrentXml ? await props.getCurrentXml() : null;
		if (!currentXml) {
			emit("error", { title: "Error", message: "Could not get the current diagram XML.", theme: "red" });
			return;
		}
		diffOldXml.value = snap.xml_content;
		diffNewXml.value = currentXml;
		diffOldLabel.value = snap.version_name
			? `${snap.version_name} — ${formatTime(snap.timestamp)}`
			: formatTime(snap.timestamp);
		diffNewLabel.value = "Current Diagram";
		diffKey.value++;
		showDiffDialog.value = true;
	} catch (error) {
		console.error("Compare failed:", error);
		emit("error", { title: "Error", message: "Failed to load version data.", theme: "red" });
	}
}

async function restoreVersion(versionName) {
	openMenu.value = null;
	if (!window.confirm("Restore this version? Your current diagram will be replaced (a snapshot of it is kept in history).")) {
		return;
	}
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.restore_version",
			params: { version_name: versionName },
		});
		const data = res.message || res;
		emit("restored", { xml: data.xml_content });
		await load();
	} catch (error) {
		console.error("Restore failed:", error);
		emit("error", { title: "Error", message: "Failed to restore version.", theme: "red" });
	}
}

function openNameDialog(group) {
	openMenu.value = null;
	nameTarget.value = group;
	nameInput.value = group.version_name || "";
	showNameDialog.value = true;
}

async function submitName() {
	if (!nameTarget.value) return;
	savingName.value = true;
	try {
		await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.name_version",
			params: { version_name: nameTarget.value.head, name: nameInput.value.trim() },
		});
		showNameDialog.value = false;
		await load();
	} catch (error) {
		console.error("Name version failed:", error);
		emit("error", { title: "Error", message: "Failed to name version.", theme: "red" });
	} finally {
		savingName.value = false;
	}
}

function formatTime(ts) {
	if (!ts) return "";
	return dayjs(ts).format("MMM D, h:mm A");
}

function dateLabel(ts) {
	if (!ts) return "";
	const d = dayjs(ts);
	if (d.isSame(dayjs(), "day")) return "Today";
	if (d.isSame(dayjs().subtract(1, "day"), "day")) return "Yesterday";
	return d.format("MMMM D, YYYY");
}

// Close the per-version menu when clicking elsewhere.
function onDocClick() {
	openMenu.value = null;
}

onMounted(() => {
	document.addEventListener("click", onDocClick);
	load();
});
onUnmounted(() => document.removeEventListener("click", onDocClick));

watch(() => props.modelName, () => load());

defineExpose({ load });
</script>
