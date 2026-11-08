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
import { useDocu } from "@/composables/useDocu";

const {
	contentCount,
	appliedName,
	saveState,
	canChange,
	saveError,
	listingQuestion,
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
