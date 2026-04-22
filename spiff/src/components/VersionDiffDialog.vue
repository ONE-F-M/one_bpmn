<template>
	<!-- Version Picker Dialog -->
	<Dialog v-model="showPickerDialog" :options="{ title: 'Compare Versions', size: 'lg' }">
		<template #body-content>
			<div class="space-y-3">
				<div class="text-sm text-gray-500">
					Select a deployed version to compare against the current diagram.
				</div>

				<!-- Loading -->
				<div v-if="loadingVersions" class="p-8 text-center text-gray-400">
					<div class="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-400 mx-auto mb-2"></div>
					Loading deployed versions...
				</div>

				<!-- Empty state -->
				<div v-else-if="versions.length === 0" class="p-8 text-center text-gray-400">
					<Icon icon="lucide:history" class="w-10 h-10 mx-auto mb-2 opacity-50" />
					<p>No other deployed versions found.</p>
					<p class="text-xs mt-1">Deploy this diagram to different models to build version history.</p>
				</div>

				<!-- Version list -->
				<div v-else class="max-h-80 overflow-y-auto border border-gray-200 rounded-lg">
					<div
						v-for="version in versions"
						:key="version.model_name"
						role="button"
						tabindex="0"
						@click="selectedVersion = version"
						@keydown.enter.prevent="selectedVersion = version"
						@keydown.space.prevent="selectedVersion = version"
						:class="[
							'flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 last:border-b-0 transition-colors',
							selectedVersion?.model_name === version.model_name
								? 'bg-blue-50 border-l-4 border-l-blue-500'
								: 'hover:bg-gray-50'
						]"
					>
						<div>
							<div class="flex items-center gap-2">
								<span class="text-sm font-medium text-gray-900">
									Version {{ version.version }}
								</span>
								<span
									v-if="version.is_active"
									class="px-1.5 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-medium"
								>
									Active
								</span>
							</div>
							<div class="text-xs text-gray-500 mt-0.5">
								{{ version.title }}
								<template v-if="version.deployed_by">
									<span class="text-gray-400"> · Deployed by {{ version.deployed_by }}</span>
								</template>
								<template v-if="version.deployed_at">
									<span class="text-gray-400"> · {{ relativeTime(version.deployed_at) }}</span>
								</template>
							</div>
						</div>
						<Icon
							v-if="selectedVersion?.model_name === version.model_name"
							icon="lucide:check-circle"
							class="w-5 h-5 text-blue-500"
						/>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button variant="subtle" @click="showPickerDialog = false">Cancel</Button>
				<Button
					variant="solid"
					@click="startComparison"
					:disabled="!selectedVersion"
					:loading="loadingDiffXml"
				>Compare</Button>
			</div>
		</template>
	</Dialog>

	<!-- Diff Viewer Dialog -->
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
				/>
			</div>
		</template>
		<template #actions>
			<Button variant="subtle" @click="showDiffDialog = false">Close</Button>
		</template>
	</Dialog>
</template>

<script setup>
import { ref } from "vue";
import { frappeRequest } from "frappe-ui";
import { Icon } from "@iconify/vue";
import { dayjs } from "@/dayjs";
import DiffViewer from "@/components/DiffViewer.vue";

const props = defineProps({
	/** BPMN Process Model document name (activeDiagramName) */
	diagramName: { type: String, default: null },
});

const emit = defineEmits(["error"]);

// ── Picker state ──
const showPickerDialog = ref(false);
const versions = ref([]);
const selectedVersion = ref(null);
const loadingVersions = ref(false);
const loadingDiffXml = ref(false);

// ── Diff state ──
const showDiffDialog = ref(false);
const diffOldXml = ref("");
const diffNewXml = ref("");
const diffOldLabel = ref("");
const diffNewLabel = ref("");
const diffKey = ref(0);

// Current XML getter — set by the parent before opening
let getCurrentXml = null;

/**
 * Open the version picker dialog.
 * @param {Function} xmlGetter — async fn that returns the current diagram XML
 */
async function open(xmlGetter) {
	if (!props.diagramName) return;

	getCurrentXml = xmlGetter;
	selectedVersion.value = null;
	versions.value = [];
	loadingVersions.value = true;
	showPickerDialog.value = true;

	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_diagram_versions",
			params: { name: props.diagramName },
		});
		versions.value = response.message || response || [];
	} catch (error) {
		console.error("Failed to load version history:", error);
		versions.value = [];
		emit("error", { title: "Error", message: "Failed to load version history.", theme: "red" });
	} finally {
		loadingVersions.value = false;
	}
}

async function startComparison() {
	if (!selectedVersion.value || !props.diagramName) return;

	loadingDiffXml.value = true;
	try {
		const response = await frappeRequest({
			url: "/api/method/one_bpmn.api.get_diagram_version_xml",
			params: {
				name: props.diagramName,
				model_name: selectedVersion.value.model_name,
			},
		});
		const data = response.message || response;

		if (!data.xml_content) {
			emit("error", { title: "Error", message: "Could not retrieve the XML for this version.", theme: "red" });
			return;
		}

		// Get the current diagram XML from the parent
		let currentXml;
		if (getCurrentXml) {
			currentXml = await getCurrentXml();
		}

		if (!currentXml) {
			emit("error", { title: "Error", message: "Could not get the current diagram XML.", theme: "red" });
			return;
		}

		// Set diff data
		diffOldXml.value = data.xml_content;
		diffNewXml.value = currentXml;
		diffOldLabel.value = `Version ${selectedVersion.value.version} — ${selectedVersion.value.title}`;
		diffNewLabel.value = "Current Diagram";
		diffKey.value++;

		// Close picker, open diff viewer
		showPickerDialog.value = false;
		showDiffDialog.value = true;
	} catch (error) {
		console.error("Failed to start diff comparison:", error);
		emit("error", { title: "Error", message: "Failed to load version data: " + (error.message || error), theme: "red" });
	} finally {
		loadingDiffXml.value = false;
	}
}

function relativeTime(timestamp) {
	if (!timestamp) return "";
	return dayjs(timestamp).fromNow();
}

defineExpose({ open });
</script>
