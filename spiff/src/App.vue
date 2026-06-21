<template>
	<div class="h-screen flex bg-gray-100 overflow-hidden relative">
		<!-- Mobile Header Toggle (Only visible on small screens, hidden on Editor routes) -->
		<div v-if="!isEditorRoute" class="lg:hidden fixed top-0 left-0 right-0 h-14 bg-white border-b flex items-center justify-between px-4 z-[100] shadow-sm">
			<div class="flex items-center gap-3">
				<div class="w-8 h-8 rounded bg-gray-900 flex items-center justify-center">
					<Icon icon="lucide:workflow" class="w-5 h-5 text-white" />
				</div>
				<span class="font-bold text-gray-900 text-sm tracking-tight uppercase">ONE BPMN</span>
			</div>
			<button 
				@click="isMobileMenuOpen = !isMobileMenuOpen"
				class="p-2 hover:bg-gray-100 rounded-md transition-colors text-gray-600"
			>
				<Icon :icon="isMobileMenuOpen ? 'lucide:x' : 'lucide:menu'" class="w-6 h-6" />
			</button>
		</div>

		<!-- Sidebar (Desktop and Mobile Overlay) -->
		<!-- Overlay Backdrop for Mobile -->
		<transition name="fade">
			<div 
				v-if="isMobileMenuOpen" 
				class="lg:hidden fixed inset-0 bg-black/40 z-[110] backdrop-blur-sm"
				@click="isMobileMenuOpen = false"
			></div>
		</transition>

		<aside
			:class="[
				'bg-white border-r flex flex-col transition-all duration-300 ease-in-out',
				// Desktop logic (Persistent on lg screens)
				collapsed ? 'lg:w-14' : 'lg:w-52',
				// Mobile logic (Drawer on < lg screens)
				!isMobileMenuOpen ? '-translate-x-full lg:translate-x-0' : 'translate-x-0',
				'fixed inset-y-0 left-0 z-[120] lg:static lg:flex h-full shrink-0'
			]"
		>
			<!-- Header -->
			<div class="border-b hidden lg:flex items-center overflow-hidden h-[48px]" :class="collapsed ? 'p-3 justify-center' : 'pl-3 pr-6'">
				<h2
					class="text-[11px] font-bold text-gray-400 font-sans uppercase tracking-widest whitespace-nowrap transition-opacity duration-200"
					:class="collapsed ? 'opacity-0 w-0' : 'opacity-100'"
				>
					ONE BPMN
				</h2>
				<Icon
					v-if="collapsed"
					icon="lucide:workflow"
					class="w-5 h-5 text-gray-500 flex-shrink-0"
				/>
			</div>

			<!-- Mobile Sidebar Header (Only visible in mobile drawer) -->
			<div class="lg:hidden p-6 border-b flex items-center gap-3">
				<div class="w-10 h-10 rounded-lg bg-gray-900 flex items-center justify-center shadow-lg text-white">
					<Icon icon="lucide:workflow" class="w-6 h-6" />
				</div>
				<span class="font-extrabold text-gray-900 text-lg uppercase tracking-wider">ONE BPMN</span>
			</div>

			<!-- Navigation -->
			<nav class="flex-1 overflow-y-auto pt-4" :class="collapsed ? 'px-1.5' : 'px-4'">
				<router-link
					to="/processa"
					class="flex items-center rounded-lg transition-all duration-200 mb-1"
					:class="[
						collapsed ? 'justify-center p-2.5' : 'gap-3 px-4 py-2.5',
						$route.path === '/processa' ? 'bg-gray-900 text-white shadow-md' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
					]"
					@click="isMobileMenuOpen = false"
					:title="collapsed ? 'Processes' : ''"
				>
					<Icon icon="lucide:layout-grid" class="w-5 h-5 shrink-0" />
					<span
						class="text-sm font-semibold whitespace-nowrap transition-opacity duration-200 overflow-hidden"
						:class="collapsed ? 'opacity-0 w-0' : 'opacity-100 w-auto'"
					>
						Processes
					</span>
				</router-link>
				<router-link
					to="/processa/process-view"
					class="flex items-center rounded-lg transition-all duration-200 mb-1"
					:class="[
						collapsed ? 'justify-center p-2.5' : 'gap-3 px-4 py-2.5',
						$route.path.startsWith('/processa/process-view') ? 'bg-gray-900 text-white shadow-md' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
					]"
					@click="isMobileMenuOpen = false"
					:title="collapsed ? 'Process View' : ''"
				>
					<Icon icon="lucide:layers" class="w-5 h-5 shrink-0" />
					<span
						class="text-sm font-semibold whitespace-nowrap transition-opacity duration-200 overflow-hidden"
						:class="collapsed ? 'opacity-0 w-0' : 'opacity-100 w-auto'"
					>
						Process View
					</span>
				</router-link>
				<router-link
					to="/processa/instances"
					class="flex items-center rounded-lg transition-all duration-200"
					:class="[
						collapsed ? 'justify-center p-2.5' : 'gap-3 px-4 py-2.5',
						$route.path === '/processa/instances' ? 'bg-gray-900 text-white shadow-md' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
					]"
					@click="isMobileMenuOpen = false"
					:title="collapsed ? 'Instances' : ''"
				>
					<Icon icon="lucide:list-todo" class="w-5 h-5 shrink-0" />
					<span
						class="text-sm font-semibold whitespace-nowrap transition-opacity duration-200 overflow-hidden"
						:class="collapsed ? 'opacity-0 w-0' : 'opacity-100 w-auto'"
					>
						Instances
					</span>
				</router-link>
			</nav>

			<!-- Collapse Toggle -->
			<div class="border-t p-4" :class="collapsed ? 'flex justify-center' : ''">

				<button
					type="button"
					@click="toggleCollapse"
					class="flex items-center w-full rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-all duration-200"
					:class="collapsed ? 'justify-center p-2' : 'gap-3 px-3 py-2'"
					:title="collapsed ? 'Expand' : 'Collapse'"
				>
					<Icon
						:icon="collapsed ? 'lucide:panel-right-close' : 'lucide:panel-left-close'"
						class="w-5 h-5 shrink-0 transition-transform duration-300"
					/>
					<span
						class="text-sm font-medium whitespace-nowrap transition-opacity duration-200 overflow-hidden"
						:class="collapsed ? 'opacity-0 w-0' : 'opacity-100 w-auto'"
					>
						Collapse Sidebar
					</span>
				</button>
			</div>
		</aside>

		<!-- Main Content -->
		<div class="flex-1 flex flex-col overflow-hidden lg:pt-0" :class="isEditorRoute ? 'pt-0' : 'pt-14'">
			<router-view />
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, provide } from "vue"
import { useRoute } from "vue-router"
import { Icon } from "@iconify/vue"

const route = useRoute()
const collapsed = ref(false)
const isMobileMenuOpen = ref(false)

// Expose sidebar toggle for child views that hide the default mobile header
provide("toggleMobileSidebar", () => {
	isMobileMenuOpen.value = !isMobileMenuOpen.value
})

// Hide the App-level mobile header on Editor routes to recover 56px of vertical space
const isEditorRoute = computed(() => {
	return route.name === "ProcessEditor" || route.name === "DiagramEditor"
})

onMounted(() => {
	const saved = localStorage.getItem("one_bpmn_sidebar_collapsed")
	if (saved === "true") {
		collapsed.value = true
	}
})

function toggleCollapse() {
	collapsed.value = !collapsed.value
	localStorage.setItem("one_bpmn_sidebar_collapsed", String(collapsed.value))
}
</script>

<style>
/* Sidebar Transitions */
.fade-enter-active, .fade-leave-active {
	transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
	opacity: 0;
}

#app {
	isolation: isolate;
	position: relative;
}
.dialog-overlay {
	z-index: 50 !important;
}
</style>
