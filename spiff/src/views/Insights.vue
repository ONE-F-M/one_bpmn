<template>
	<div class="h-full flex flex-col bg-gray-50">
		<!-- Header -->
		<header class="bg-white border-b px-6 py-4 flex items-center justify-between">
			<div class="flex items-center gap-4">
				<h1 class="text-xl font-semibold text-gray-900">AI Insights</h1>
				<!-- Origin segment: production traffic vs eval runs (WI-001751) -->
				<div class="flex rounded-lg border border-gray-200 overflow-hidden">
					<button
						v-for="seg in originSegments"
						:key="seg.value"
						@click="origin = seg.value"
						class="px-3 py-1.5 text-xs font-medium transition-colors"
						:class="origin === seg.value ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'"
					>
						{{ seg.label }}
					</button>
				</div>
			</div>
			<div class="flex items-center gap-3">
				<FormControl
					type="date"
					v-model="fromDate"
					class="w-40"
				/>
				<span class="text-sm text-gray-400">to</span>
				<FormControl
					type="date"
					v-model="toDate"
					class="w-40"
				/>
			</div>
		</header>

		<!-- Content -->
		<main class="flex-1 p-6 overflow-auto space-y-6">
			<!-- Overview Cards -->
			<OverviewCards :origin="origin" />

			<!-- Tabs + Report Content -->
			<div class="bg-white rounded-lg shadow-sm">
				<!-- Tab bar -->
				<div class="border-b px-2 flex">
					<button
						v-for="tab in tabs"
						:key="tab.key"
						@click="activeTab = tab.key"
						class="px-4 py-3 text-sm font-medium transition-colors relative"
						:class="activeTab === tab.key
							? 'text-gray-900'
							: 'text-gray-500 hover:text-gray-700'"
					>
						<div class="flex items-center gap-2">
							<Icon :icon="tab.icon" class="w-4 h-4" />
							<span>{{ tab.label }}</span>
						</div>
						<div
							v-if="activeTab === tab.key"
							class="absolute bottom-0 left-0 right-0 h-0.5 bg-gray-900"
						></div>
					</button>
				</div>

				<!-- Tab content -->
				<div class="p-6">
					<CostTokenReport
						v-if="activeTab === 'cost'"
						:from-date="fromDate"
						:to-date="toDate"
						:origin="origin"
					/>
					<ErrorReport
						v-if="activeTab === 'errors'"
						:from-date="fromDate"
						:to-date="toDate"
						:origin="origin"
					/>
					<PerformanceReport
						v-if="activeTab === 'performance'"
						:from-date="fromDate"
						:to-date="toDate"
						:origin="origin"
					/>
					<CostAllocationReport
						v-if="activeTab === 'allocation'"
						:from-date="fromDate"
						:to-date="toDate"
					/>
				</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { ref } from "vue"
import { FormControl } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { dayjs } from "@/dayjs"

import OverviewCards from "@/components/insights/OverviewCards.vue"
import CostTokenReport from "@/components/insights/CostTokenReport.vue"
import ErrorReport from "@/components/insights/ErrorReport.vue"
import PerformanceReport from "@/components/insights/PerformanceReport.vue"
import CostAllocationReport from "@/components/insights/CostAllocationReport.vue"

const activeTab = ref("cost")

const fromDate = ref(dayjs().subtract(6, "day").format("YYYY-MM-DD"))
const toDate = ref(dayjs().format("YYYY-MM-DD"))

// Run-origin segment (WI-001751): production traffic, eval runs, or both.
const origin = ref("production")
const originSegments = [
	{ label: "Production", value: "production" },
	{ label: "Evals", value: "eval" },
	{ label: "All", value: "all" },
]

const tabs = [
	{ key: "cost", label: "Cost & Tokens", icon: "lucide:credit-card" },
	{ key: "errors", label: "Errors", icon: "lucide:alert-triangle" },
	{ key: "performance", label: "Performance", icon: "lucide:timer" },
	{ key: "allocation", label: "Cost Allocation", icon: "lucide:receipt" },
]
</script>
