<template>
	<ul v-if="childChanges.length" class="dc-child-changes">
		<li v-for="line in childChanges" :key="line">{{ line }}</li>
	</ul>

	<div v-if="saveState === 'pending'" class="dc-pending-banner" role="status">
		<strong>Awaiting approval.</strong>
		<template v-if="pendingParts"
			>{{ pendingParts.before
			}}<a :href="pendingUrl" target="_blank" rel="noopener">{{ pendingRequest }}</a
			>{{ pendingParts.after }}</template
		>
		<template v-else>{{ pendingNotice }}</template>
	</div>
</template>

<script setup>
import { useDocu } from "@/composables/useDocu";

const { saveState, pendingNotice, pendingRequest, pendingParts, pendingUrl, childChanges } =
	useDocu();
</script>

<style scoped src="@/components/Docu/docuChangesPreview.css"></style>
