<template>
	<div class="h-screen flex bg-gray-100">
		<!-- Global Sidebar -->
		<aside
			class="bg-white border-r flex flex-col transition-all duration-300 ease-in-out"
			:class="collapsed ? 'w-[60px]' : 'w-64'"
		>
			<!-- Header -->
			<div class="border-b flex items-center overflow-hidden" :class="collapsed ? 'p-4 justify-center' : 'p-6'">
				<h2
					class="text-sm font-bold text-gray-500 uppercase tracking-wider whitespace-nowrap transition-opacity duration-200"
					:class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'"
				>
					ONE BPMN
				</h2>
				<Icon
					v-if="collapsed"
					icon="lucide:workflow"
					class="w-5 h-5 text-gray-500 flex-shrink-0"
				/>
			</div>

			<!-- Navigation -->
			<nav class="flex-1 space-y-1" :class="collapsed ? 'p-2' : 'p-4'">
				<router-link
					to="/processa"
					class="flex items-center rounded-md transition-colors"
					:class="[
						collapsed ? 'justify-center px-2 py-2' : 'gap-3 px-3 py-2',
						$route.path === '/processa' ? 'bg-gray-100 text-gray-900' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
					]"
					:title="collapsed ? 'Processes' : ''"
				>
					<Icon icon="lucide:layout-grid" class="w-5 h-5 flex-shrink-0" />
					<span
						class="text-sm font-medium whitespace-nowrap transition-opacity duration-200"
						:class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'"
					>
						Processes
					</span>
				</router-link>
				<router-link
					to="/processa/instances"
					class="flex items-center rounded-md transition-colors"
					:class="[
						collapsed ? 'justify-center px-2 py-2' : 'gap-3 px-3 py-2',
						$route.path === '/processa/instances' ? 'bg-gray-100 text-gray-900' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
					]"
					:title="collapsed ? 'Instances' : ''"
				>
					<Icon icon="lucide:list-todo" class="w-5 h-5 flex-shrink-0" />
					<span
						class="text-sm font-medium whitespace-nowrap transition-opacity duration-200"
						:class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'"
					>
						Instances
					</span>
				</router-link>
			</nav>

			<!-- Collapse Toggle -->
			<div class="border-t" :class="collapsed ? 'p-2' : 'p-4'">
				<button
					type="button"
					@click="toggleCollapse"
					class="flex items-center w-full rounded-md text-gray-500 hover:bg-gray-50 hover:text-gray-700 transition-colors"
					:class="collapsed ? 'justify-center px-2 py-2' : 'gap-3 px-3 py-2'"
					:title="collapsed ? 'Expand' : 'Collapse'"
				>
					<Icon
						:icon="collapsed ? 'lucide:panel-right-close' : 'lucide:panel-left-close'"
						class="w-5 h-5 flex-shrink-0 transition-transform duration-300"
					/>
					<span
						class="text-sm font-medium whitespace-nowrap transition-opacity duration-200"
						:class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'"
					>
						Collapse
					</span>
				</button>
			</div>
		</aside>

		<!-- Main Content -->
		<div class="flex-1 flex flex-col overflow-hidden">
			<router-view />
		</div>
	</div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { Icon } from "@iconify/vue"


const collapsed = ref(false)

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
#app {
	isolation: isolate;
	position: relative;
}
.dialog-overlay {
	z-index: 50 !important;
}
</style>
