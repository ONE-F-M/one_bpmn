<template>
	<div class="h-10 sm:h-12 flex items-center px-3 gap-1 relative">
		<!-- Add tab button (hidden in read-only mode) -->
		<button
			v-if="!readonly"
			@click="$emit('add-tab')"
			class="p-2 rounded hover:bg-gray-300 text-gray-600 shrink-0"
			title="Create new version"
		>
			<Icon icon="lucide:plus" class="w-5 h-5" />
		</button>

		<!-- Compare button (Material Design 3 'compare' icon) -->
		<button
			@click="$emit('compare')"
			class="p-2 rounded hover:bg-gray-300 text-gray-600 shrink-0"
			title="Compare versions"
		>
			<Icon icon="material-symbols:compare" class="w-5 h-5" />
		</button>

		<!-- All Tabs Menu -->
		<div class="relative shrink-0">
			<button
				@click="showAllTabsMenu = !showAllTabsMenu"
				class="p-2 rounded hover:bg-gray-300 text-gray-600 transition-colors"
				title="All diagrams"
			>
				<Icon icon="lucide:menu" class="w-5 h-5" />
			</button>
			<div
				v-if="showAllTabsMenu"
				v-click-outside="() => showAllTabsMenu = false"
				class="absolute left-0 bottom-full mb-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1 max-h-80 overflow-y-auto"
			>
				<button
					v-for="tab in tabs"
					:key="tab.name"
					@click="$emit('select-tab', tab.name); showAllTabsMenu = false"
					class="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
					:class="{ 'bg-gray-50 font-semibold text-gray-900': activeTab === tab.name }"
				>
					<span
						:class="[
							'w-2 h-2 rounded-full shrink-0',
							tab.is_active ? 'bg-green-500' : 'bg-orange-500'
						]"
					></span>
					<span class="truncate">{{ tab.model_name }}</span>
				</button>
			</div>
		</div>

		<!-- Scrollable Tab Container -->
		<div ref="scrollContainerRef" class="flex-1 flex items-center gap-1 overflow-x-auto no-scrollbar py-2 tab-scroll-fade" style="-webkit-overflow-scrolling: touch; scroll-snap-type: x proximity;">
			<!-- Tabs -->
			<div
				v-for="tab in tabs"
				:key="tab.name"
				:data-tab-active="activeTab === tab.name ? 'true' : undefined"
				style="scroll-snap-align: center;"
				:class="[
					'flex items-center gap-2 pl-4 pr-1 py-1.5 rounded text-sm cursor-pointer transition-colors shrink-0 group',
					activeTab === tab.name
						? 'bg-gray-700 text-white shadow-sm'
						: 'bg-transparent text-gray-600 hover:bg-gray-200'
				]"
				@click="$emit('select-tab', tab.name)"
				@dblclick.stop="!readonly && startEditing(tab)"
			>
				<!-- Status dot -->
				<span
					:class="[
						'inline-block w-2 h-2 rounded-full shrink-0',
						tab.is_active ? 'bg-green-400' : 'bg-orange-400'
					]"
				></span>

				<!-- Inline rename input -->
				<input
					v-if="editingTab === tab.name"
					ref="renameInputRef"
					v-model="editingName"
					type="text"
					class="bg-transparent border-b border-white/60 text-inherit text-sm outline-none px-0 py-0 w-32"
					@blur="finishEditing(tab)"
					@keydown.enter.prevent="finishEditing(tab)"
					@keydown.escape.prevent="cancelEditing"
					@click.stop
				/>
				<span v-else class="truncate max-w-40">{{ tab.model_name }}</span>

				<!-- Tab Kebab Menu -->
				<div v-if="editingTab !== tab.name && !readonly" class="relative">
					<button
						@click.stop="toggleTabMenu(tab, $event)"
						class="p-1 rounded opacity-50 hover:opacity-100 hover:bg-black/10 transition-all tab-menu-trigger"
					>
						<Icon icon="lucide:more-vertical" class="w-4 h-4" />
					</button>
				</div>
			</div>

			<!-- Divider between map tabs and named-version chips -->
			<div
				v-if="versions.length"
				class="self-stretch w-px bg-gray-300 mx-1 shrink-0"
			></div>

			<!-- Named-version chips (read-only; darker to distinguish from map tabs) -->
			<div
				v-for="v in versions"
				:key="v.name"
				:data-tab-active="activeVersion === v.name ? 'true' : undefined"
				style="scroll-snap-align: center;"
				:class="[
					'flex items-center gap-1.5 px-3 py-1.5 rounded text-sm cursor-pointer transition-colors shrink-0',
					activeVersion === v.name
						? 'bg-gray-900 text-white shadow-sm'
						: 'bg-gray-200 text-gray-700 hover:bg-gray-300'
				]"
				:title="`Named version — read only`"
				@click="$emit('select-version', v.name)"
			>
				<Icon icon="lucide:lock" class="w-3 h-3 shrink-0 opacity-70" />
				<span class="truncate max-w-40">{{ v.version_name }}</span>
			</div>
		</div>

		<!-- Single Tab Dropdown (positioned dynamically to avoid clipping) -->
		<div
			v-if="activeMenu && activeMenuTab"
			v-click-outside="() => { activeMenu = null; activeMenuTab = null }"
			:style="menuStyle"
			class="fixed w-32 bg-white border border-gray-200 rounded-lg shadow-lg z-[100] py-1"
		>
			<button
				@click.stop="startEditingFromMenu(activeMenuTab)"
				class="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 transition-colors"
			>
				<Icon icon="lucide:pencil" class="w-3.5 h-3.5" />
				Rename
			</button>
			<button
				@click.stop="duplicateTab(activeMenuTab)"
				class="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 transition-colors"
			>
				<Icon icon="lucide:copy" class="w-3.5 h-3.5" />
				Duplicate
			</button>
			<button
				@click.stop="deleteTab(activeMenuTab)"
				class="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 transition-colors"
			>
				<Icon icon="lucide:trash-2" class="w-3.5 h-3.5" />
				Delete
			</button>
		</div>
	</div>
</template>

<script setup>
import { ref, nextTick, computed, onMounted, onUnmounted, watch } from "vue"
import { Icon } from "@iconify/vue"

const props = defineProps({
	tabs: {
		type: Array,
		default: () => []
	},
	activeTab: {
		type: String,
		default: null
	},
	readonly: {
		type: Boolean,
		default: false
	},
	// Named versions shown as read-only chips beside the map tabs.
	versions: {
		type: Array,
		default: () => []
	},
	// Name (snapshot doc) of the named version currently being viewed.
	activeVersion: {
		type: String,
		default: null
	}
})

const emit = defineEmits([
	"select-tab",
	"add-tab",
	"rename-tab",
	"duplicate-tab",
	"delete-tab",
	"select-version",
	"compare",
])

const editingTab = ref(null)
const editingName = ref("")
const renameInputRef = ref(null)
const activeMenu = ref(null) // Stores tab name
const activeMenuTab = ref(null) // Stores tab object
const menuPosition = ref({ top: 0, left: 0 })
const showAllTabsMenu = ref(false)
const scrollContainerRef = ref(null)

// Auto-scroll active tab into view when it changes
watch(() => props.activeTab, () => {
	nextTick(() => {
		if (!scrollContainerRef.value) return
		const activeEl = scrollContainerRef.value.querySelector('[data-tab-active="true"]')
		if (activeEl) {
			activeEl.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" })
		}
	})
})

const menuStyle = computed(() => ({
	top: `${menuPosition.value.top}px`,
	left: `${menuPosition.value.left}px`,
	transform: 'translateY(-100%)',
}))

function toggleTabMenu(tab, event) {
	if (activeMenu.value === tab.name) {
		activeMenu.value = null
		activeMenuTab.value = null
		return
	}

	const rect = event.currentTarget.getBoundingClientRect()
	menuPosition.value = {
		top: rect.top - 4, // Menu grows upward from here (translateY(-100%))
		left: rect.left     // Align left edge with the button
	}
	activeMenuTab.value = tab
	activeMenu.value = tab.name
}

// Close menu on scroll or resize
function handleScroll() {
	if (activeMenu.value) activeMenu.value = null
}

onMounted(() => {
	window.addEventListener("scroll", handleScroll, true)
	window.addEventListener("resize", handleScroll)
})

onUnmounted(() => {
	window.removeEventListener("scroll", handleScroll, true)
	window.removeEventListener("resize", handleScroll)
})

function startEditing(tab) {
	editingTab.value = tab.name
	editingName.value = tab.model_name
	activeMenu.value = null
	nextTick(() => {
		const el = renameInputRef.value?.[0] || renameInputRef.value
		if (el) {
			el.focus()
			el.select()
		}
	})
}

function startEditingFromMenu(tab) {
	startEditing(tab)
}

function duplicateTab(tab) {
	activeMenu.value = null
	emit("duplicate-tab", tab)
}

function deleteTab(tab) {
	activeMenu.value = null
	emit("delete-tab", tab)
}

function finishEditing(tab) {
	const newName = editingName.value.trim()
	const oldName = tab.model_name
	editingTab.value = null

	if (newName && newName !== oldName) {
		emit("rename-tab", {
			tabName: tab.name,
			oldModelName: oldName,
			newModelName: newName,
		})
	}
}

function cancelEditing() {
	editingTab.value = null
	editingName.value = ""
}
</script>

<style scoped>
/* Fade hint on right edge of scrollable tab container */
.tab-scroll-fade {
	mask-image: linear-gradient(
		to right,
		black 0,
		black calc(100% - 12px),
		transparent 100%
	);
	-webkit-mask-image: linear-gradient(
		to right,
		black 0,
		black calc(100% - 12px),
		transparent 100%
	);
}
</style>
