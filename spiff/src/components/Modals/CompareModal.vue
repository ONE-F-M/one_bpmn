<template>
	<!-- Compare versions dialog (opened from the compare icon in the bottom bar) -->
	<Dialog v-model="show" :options="{ title: 'Compare versions', size: '7xl' }">
		<template #body-content>
			<div class="flex flex-col gap-3" style="height: 72vh">
				<!-- Controls -->
				<div class="flex flex-wrap items-center gap-3 shrink-0">
					<div class="flex items-center gap-2">
						<span class="text-sm text-gray-600">Compare</span>
						<select
							v-model="selectedVersion"
							class="text-sm border border-gray-300 rounded-md px-3 py-1.5 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-48"
							@change="runCompare"
						>
							<option value="" disabled>Select a named version…</option>
							<option v-for="v in namedVersions" :key="v.name" :value="v.name">
								{{ v.version_name }} — {{ formatTime(v.timestamp) }}
							</option>
						</select>
						<span class="text-sm text-gray-600">with the</span>
						<span class="text-sm font-medium text-gray-900">Latest version</span>
					</div>

					<label class="flex items-center gap-2 text-sm text-gray-700 cursor-pointer ml-auto">
						<input
							type="checkbox"
							v-model="highlightChanges"
							class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
						/>
						Highlight changes
					</label>
				</div>

				<!-- Deployed comparison entry (moved here from the version-history panel) -->
				<div class="shrink-0">
					<button
						class="text-xs text-blue-600 hover:text-blue-700 hover:underline"
						@click="$emit('compare-deployed')"
					>
						Compare deployed versions…
					</button>
				</div>

				<!-- Diff area -->
				<div class="flex-1 min-h-0 border border-gray-200 rounded-lg overflow-hidden">
					<div v-if="loadingVersions" class="h-full flex items-center justify-center text-gray-400 text-sm">
						Loading named versions…
					</div>
					<div
						v-else-if="namedVersions.length === 0"
						class="h-full flex flex-col items-center justify-center text-gray-400 text-sm"
					>
						<Icon icon="lucide:history" class="w-10 h-10 mb-2 opacity-50" />
						No named versions yet. Name a version to compare it against the latest.
					</div>
					<DiffViewer
						v-else-if="diffOldXml && diffNewXml"
						:key="diffKey"
						:oldXml="diffOldXml"
						:newXml="diffNewXml"
						:oldLabel="diffOldLabel"
						:newLabel="diffNewLabel"
						:highlightChanges="highlightChanges"
					/>
					<div v-else class="h-full flex items-center justify-center text-gray-400 text-sm">
						Select a named version and click Compare.
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<Button variant="subtle" @click="show = false">Close</Button>
		</template>
	</Dialog>
</template>

<script setup>
import { ref, computed } from "vue";
import { frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import { dayjs } from "@/dayjs";
import DiffViewer from "@/components/DiffViewer.vue";

const props = defineProps({
	/** BPMN Process Model document name whose named versions are compared. */
	modelName: { type: String, default: null },
});

const emit = defineEmits(["error", "compare-deployed"]);

const show = ref(false);
const loadingVersions = ref(false);
const loadingDiff = ref(false);
const namedVersions = ref([]);
const selectedVersion = ref("");
const highlightChanges = ref(true);

const diffOldXml = ref("");
const diffNewXml = ref("");
const diffOldLabel = ref("");
const diffNewLabel = ref("");
const diffKey = ref(0);

// Provided by the parent on open() — returns the latest (current) diagram XML.
let getCurrentXml = null;

/**
 * Open the compare dialog.
 * @param {Function} xmlGetter — async fn returning the latest diagram XML.
 */
async function open(xmlGetter) {
	getCurrentXml = xmlGetter;
	selectedVersion.value = "";
	diffOldXml.value = "";
	diffNewXml.value = "";
	namedVersions.value = [];
	show.value = true;
	await loadNamedVersions();
	// Auto-compare against the most recent named version for convenience.
	if (selectedVersion.value) await runCompare();
}

async function loadNamedVersions() {
	if (!props.modelName) return;
	loadingVersions.value = true;
	try {
		const res = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_edit_history",
			params: { model_name: props.modelName },
		});
		const groups = res.message || res || [];
		namedVersions.value = groups
			.filter((g) => g.is_named)
			.map((g) => ({ name: g.head, version_name: g.version_name, timestamp: g.timestamp }));
		if (namedVersions.value.length) selectedVersion.value = namedVersions.value[0].name;
	} catch (error) {
		console.error("Failed to load named versions:", error);
		emit("error", { title: "Error", message: "Failed to load named versions.", theme: "red" });
	} finally {
		loadingVersions.value = false;
	}
}

async function runCompare() {
	if (!selectedVersion.value) return;
	loadingDiff.value = true;
	try {
		const snapRes = await frappeRequest({
			url: "/api/method/one_bpmn.api.version_history.get_snapshot_xml",
			params: { version_name: selectedVersion.value },
		});
		const snap = snapRes.message || snapRes;
		if (!snap.xml_content) {
			emit("error", { title: "Error", message: "Could not retrieve this version's XML.", theme: "red" });
			return;
		}
		const currentXml = getCurrentXml ? await getCurrentXml() : null;
		if (!currentXml) {
			emit("error", { title: "Error", message: "Could not get the latest diagram XML.", theme: "red" });
			return;
		}
		diffOldXml.value = snap.xml_content;
		diffNewXml.value = currentXml;
		diffOldLabel.value = snap.version_name
			? `${snap.version_name} — ${formatTime(snap.timestamp)}`
			: formatTime(snap.timestamp);
		diffNewLabel.value = "Latest version";
		diffKey.value++;
	} catch (error) {
		console.error("Compare failed:", error);
		emit("error", { title: "Error", message: "Failed to compare versions.", theme: "red" });
	} finally {
		loadingDiff.value = false;
	}
}

function formatTime(ts) {
	if (!ts) return "";
	return dayjs(ts).format("MMM D, h:mm A");
}

const isAnyDialogOpen = computed(() => show.value);

defineExpose({ open, isAnyDialogOpen });
</script>
