<template>
	<div class="h-screen flex bg-gray-100">
		<!-- Global Sidebar -->
		<aside class="w-64 bg-white border-r flex flex-col">
			<div class="p-6 border-b">
				<h2 class="text-sm font-bold text-gray-500 uppercase tracking-wider">ONE BPMN</h2>
			</div>
			<nav class="flex-1 p-4 space-y-1">
				<a
					href="javascript:void(0)"
					@click="router.push('/processa')"
					class="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors"
					:class="[$route.path === '/processa' ? 'bg-gray-100 text-gray-900' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900']"
				>
					<Icon icon="lucide:layout-grid" class="w-5 h-5 flex-shrink-0" />
					Processes
				</a>
				<a
					href="javascript:void(0)"
					@click="router.push('/processa/instances')"
					class="flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors"
					:class="[$route.path === '/processa/instances' ? 'bg-gray-100 text-gray-900' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900']"
				>
					<Icon icon="lucide:list-todo" class="w-5 h-5 flex-shrink-0" />
					Instances
				</a>
			</nav>
			<div class="p-4 border-t text-xs text-gray-400">
				
			</div>
		</aside>

		<!-- Main Content -->
		<div class="flex-1 flex flex-col overflow-hidden">
			<router-view />
		</div>
	</div>
</template>

<script setup>
import { Icon } from "@iconify/vue"
import { useRouter } from "vue-router"

const router = useRouter()
</script>
