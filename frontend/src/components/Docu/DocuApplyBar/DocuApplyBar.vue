<template>
	<div class="dc-window-footer">
		<span class="dc-count">{{ contentCount }} field{{ contentCount === 1 ? "" : "s" }}</span>
		<span class="dc-save-status" :class="'st-' + saveState">
			<template v-if="!canChange">Read only: you are not allowed to change forms</template>
			<template v-else-if="saveState === 'saving'">Saving…</template>
			<template v-else-if="saveState === 'saved'"
				>✓ Saved{{ appliedName ? " “" + appliedName + "”" : "" }}</template
			>
			<template v-else-if="saveState === 'error'">⚠ {{ saveError }}</template>
			<template v-else-if="saveState === 'pending' && pendingParts"
				>{{ pendingParts.before
				}}<a :href="pendingUrl" target="_blank" rel="noopener">{{ pendingRequest }}</a
				>{{ pendingParts.after }}</template
			>
			<template v-else-if="saveState === 'pending'">{{ pendingNotice }}</template>
			<template v-else-if="saveState === 'placement'">
				{{ placementQuestion }}
				<select
					:value="dtApp"
					class="dc-placement-select"
					@change="pickApp($event.target.value)"
				>
					<option value="" disabled>App</option>
					<option v-for="a in apps" :key="a" :value="a">{{ a }}</option>
				</select>
				<select v-model="dtModule" class="dc-placement-select" :disabled="!dtApp">
					<option value="" disabled>Module</option>
					<option v-for="m in moduleOptions" :key="m" :value="m">{{ m }}</option>
				</select>
			</template>
			<template v-else-if="saveState === 'question'">
				{{ listingQuestion }}
				<button class="dc-option-btn" @click="answerListing(true)">Yes</button>
				<button class="dc-option-btn" @click="answerListing(false)">No</button>
			</template>
			<template v-else>Changes save automatically</template>
		</span>
		<span v-if="saveNotes" class="dc-save-status">{{ saveNotes }}</span>
		<Button v-if="unsavedDesign" size="sm" @click="restoreUnsavedDesign">
			Restore my unsaved design
		</Button>
	</div>
</template>

<script setup>
import { Button } from "frappe-ui";
import { useDocu } from "@/composables/Docu/useDocu";

const {
	contentCount,
	appliedName,
	saveState,
	canChange,
	saveError,
	listingQuestion,
	placementQuestion,
	dtApp,
	dtModule,
	apps,
	moduleOptions,
	pickApp,
	pendingNotice,
	pendingRequest,
	pendingParts,
	pendingUrl,
	saveNotes,
	unsavedDesign,
	answerListing,
	restoreUnsavedDesign,
} = useDocu();
</script>

<style scoped src="./DocuApplyBar.css"></style>
