<template>
	<div class="shape-library-panel h-full flex flex-col bg-white border-r border-gray-200">
		<!-- Header -->
		<div class="flex items-center justify-between px-3 py-2 border-b border-gray-200 bg-gray-50">
			<span class="text-sm font-medium text-gray-700">Shape Libraries</span>
			<div class="flex gap-1">
				<button
					@click="showCreateLibrary = true"
					class="p-1 rounded hover:bg-gray-200 text-gray-500"
					title="Create Library"
				>
					<Icon icon="lucide:folder-plus" class="w-4 h-4" />
				</button>
				<button
					@click="showImportShape = true"
					class="p-1 rounded hover:bg-gray-200 text-gray-500"
					title="Import Shape"
				>
					<Icon icon="lucide:upload" class="w-4 h-4" />
				</button>
			</div>
		</div>

		<!-- Libraries List -->
		<div class="flex-1 overflow-y-auto">
			<div v-if="loading" class="flex items-center justify-center h-32">
				<Icon icon="lucide:loader-2" class="w-5 h-5 animate-spin text-gray-400" />
			</div>

			<div v-else-if="libraries.length === 0" class="p-4 text-center text-gray-400 text-sm">
				No shape libraries yet.<br />
				Click + to create one.
			</div>

			<div v-else class="py-2">
				<div
					v-for="library in libraries"
					:key="library.name"
					class="library-section"
				>
					<!-- Library Header -->
					<button
						@click="toggleLibrary(library.name)"
						class="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
					>
						<Icon
							:icon="expandedLibraries.has(library.name) ? 'lucide:chevron-down' : 'lucide:chevron-right'"
							class="w-4 h-4 text-gray-400"
						/>
						<Icon :icon="'lucide:' + (library.icon || 'folder')" class="w-4 h-4 text-gray-500" />
						<span class="flex-1 text-left truncate">{{ library.library_name }}</span>
						<span class="text-xs text-gray-400">{{ library.shapes?.length || 0 }}</span>
					</button>

					<!-- Shapes Grid -->
					<div
						v-if="expandedLibraries.has(library.name)"
						class="grid grid-cols-2 gap-2 px-3 py-2 bg-gray-50"
					>
						<div
							v-for="shape in library.shapes"
							:key="shape.name"
							draggable="true"
							@dragstart="handleDragStart($event, shape)"
							class="shape-item p-2 bg-white border border-gray-200 rounded cursor-grab hover:border-blue-400 hover:shadow-sm transition-all"
							:title="shape.shape_name"
						>
							<div class="shape-thumbnail" v-html="shape.svg_content"></div>
							<div class="mt-1 text-xs text-center text-gray-600 truncate">
								{{ shape.shape_name }}
							</div>
						</div>

						<div
							v-if="!library.shapes || library.shapes.length === 0"
							class="col-span-2 text-xs text-gray-400 text-center py-2"
						>
							No shapes in this library
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Create Library Dialog -->
		<Dialog v-model="showCreateLibrary" :options="{ title: 'Create Shape Library' }">
			<template #body-content>
				<div class="space-y-4 bg-white">
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">Library Name</label>
						<input
							v-model="newLibraryName"
							type="text"
							placeholder="My Custom Shapes"
							class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
						/>
					</div>
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">Icon (Lucide name)</label>
						<input
							v-model="newLibraryIcon"
							type="text"
							placeholder="folder"
							class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
						/>
					</div>
				</div>
			</template>
			<template #actions>
				<Button variant="solid" @click="createLibrary" :loading="creatingLibrary">
					Create
				</Button>
			</template>
		</Dialog>

		<!-- Import Shape Dialog -->
		<Dialog v-model="showImportShape" :options="{ title: 'Import Shape' }">
			<template #body-content>
				<div class="space-y-4 bg-white">
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">Library</label>
						<select
							v-model="importShapeLibrary"
							class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white text-gray-900"
						>
							<option value="">Select library...</option>
							<option v-for="lib in libraries" :key="lib.name" :value="lib.name">
								{{ lib.library_name }}
							</option>
						</select>
					</div>
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">Shape Name</label>
						<input
							v-model="importShapeName"
							type="text"
							placeholder="My Shape"
							class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm bg-white text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
						/>
					</div>
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">SVG File</label>
						<input
							type="file"
							accept=".svg"
							@change="handleFileSelect"
							class="w-full text-sm bg-white"
						/>
						<p class="text-xs text-gray-400 mt-1">Max 150KB</p>
					</div>

				</div>
			</template>
			<template #actions>
				<Button variant="solid" @click="uploadShape" :loading="uploadingShape">
					Import
				</Button>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { Icon } from "@iconify/vue";
import { Dialog, Button, call } from "frappe-ui";

const emit = defineEmits(["shape-drag-start"]);

// State
const libraries = ref([]);
const loading = ref(true);
const expandedLibraries = ref(new Set());

// Create library dialog
const showCreateLibrary = ref(false);
const newLibraryName = ref("");
const newLibraryIcon = ref("folder");
const creatingLibrary = ref(false);

// Import shape dialog
const showImportShape = ref(false);
const importShapeLibrary = ref("");
const importShapeName = ref("");
const importShapeType = ref("bpmn_element");
const importSvgContent = ref("");
const uploadingShape = ref(false);

async function loadLibraries() {
	loading.value = true;
	try {
		const result = await call("one_bpmn.api.get_shape_libraries");
		libraries.value = result || [];
	} catch (error) {
		console.error("Failed to load shape libraries:", error);
	} finally {
		loading.value = false;
	}
}

function toggleLibrary(name) {
	if (expandedLibraries.value.has(name)) {
		expandedLibraries.value.delete(name);
	} else {
		expandedLibraries.value.add(name);
	}
}

async function createLibrary() {
	if (!newLibraryName.value) return;

	creatingLibrary.value = true;
	try {
		await call("one_bpmn.api.create_shape_library", {
			library_name: newLibraryName.value,
			icon: newLibraryIcon.value || "folder",
		});
		showCreateLibrary.value = false;
		newLibraryName.value = "";
		newLibraryIcon.value = "folder";
		await loadLibraries();
	} catch (error) {
		console.error("Failed to create library:", error);
		alert("Failed to create library: " + (error.message || error));
	} finally {
		creatingLibrary.value = false;
	}
}

function handleFileSelect(event) {
	const file = event.target.files[0];
	if (!file) return;

	if (file.size > 150 * 1024) {
		alert("File too large. Maximum size is 150KB.");
		return;
	}

	const reader = new FileReader();
	reader.onload = (e) => {
		importSvgContent.value = e.target.result;
	};
	reader.readAsText(file);
}

async function uploadShape() {
	if (!importShapeLibrary.value || !importShapeName.value || !importSvgContent.value) {
		alert("Please fill all fields and select an SVG file.");
		return;
	}

	uploadingShape.value = true;
	try {
		await call("one_bpmn.api.upload_shape", {
			library: importShapeLibrary.value,
			shape_name: importShapeName.value,
			svg_content: importSvgContent.value,
			shape_type: importShapeType.value,
		});
		showImportShape.value = false;
		importShapeLibrary.value = "";
		importShapeName.value = "";
		importSvgContent.value = "";
		importShapeType.value = "decorative";
		await loadLibraries();
	} catch (error) {
		console.error("Failed to upload shape:", error);
		alert("Failed to upload shape: " + (error.message || error));
	} finally {
		uploadingShape.value = false;
	}
}

function handleDragStart(event, shape) {
	event.dataTransfer.setData("application/json", JSON.stringify(shape));
	event.dataTransfer.effectAllowed = "copy";
	emit("shape-drag-start", shape);
}

onMounted(() => {
	loadLibraries();
});

defineExpose({
	loadLibraries,
});
</script>

<style scoped>
.shape-library-panel {
	width: 220px;
	min-width: 220px;
}

.shape-thumbnail {
	width: 100%;
	height: 48px;
	display: flex;
	align-items: center;
	justify-content: center;
	overflow: hidden;
}

.shape-thumbnail :deep(svg) {
	max-width: 100%;
	max-height: 100%;
	width: auto;
	height: auto;
	object-fit: contain;
}
</style>
