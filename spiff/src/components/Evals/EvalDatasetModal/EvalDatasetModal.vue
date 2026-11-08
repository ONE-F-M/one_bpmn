<template>
	<Dialog v-model="showDataset" :options="{ title: 'Golden dataset', size: '2xl' }">
		<template #body-content>
			<div v-if="readiness" class="space-y-4">
				<FormControl
					v-model="datasetScope"
					type="select"
					label="Reading and versioning"
					:options="DATASET_SCOPES"
					description="A version of this suite is what a run passed against. The agent's view spans every suite it has."
					@change="loadReadiness"
				/>
				<p class="text-sm text-gray-700">
					<span class="font-medium">{{ readiness.subject }}</span> carries
					<span class="font-medium">{{ readiness.cases }}</span> case(s).
					<template v-if="readiness.minimum">
						<span v-if="readiness.short_by"
							>{{ readiness.short_by }} short of {{ readiness.minimum }};</span
						>
						<span v-else>Past the {{ readiness.minimum }} mark;</span>
						<span v-if="readiness.target">{{ readiness.target }} is comfortable.</span>
					</template>
					<span v-else class="text-gray-500">
						The agent has set no minimum, so there is nothing to measure this against.
						Set one on the agent's configuration to see a bar here.
					</span>
				</p>
				<p class="text-xs text-gray-500">
					A reading, not a gate. The one hard case-count bar is a skill graduating to
					Action-Allowed.
				</p>

				<div class="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
					<div
						v-for="(count, type) in readiness.by_type"
						:key="type"
						class="flex justify-between"
					>
						<span :class="count ? 'text-gray-700' : 'text-gray-400'">{{ type }}</span>
						<span :class="count ? 'font-medium' : 'text-gray-400'">{{ count }}</span>
					</div>
				</div>

				<p v-if="readiness.missing_types.length" class="text-sm text-amber-600">
					Nothing yet for: {{ readiness.missing_types.join(", ") }}.
				</p>

				<div class="border-t border-gray-100 pt-3 text-sm">
					<p v-if="readiness.latest_version">
						Latest version
						<span class="font-medium">v{{ readiness.latest_version.version }}</span
						>, {{ readiness.latest_version.case_count }} case(s), taken
						{{ readiness.latest_version.taken_at }}.
						<span v-if="readiness.drifted_from_version" class="text-amber-600">
							The cases have changed since — take a new version to record where they
							are now.
						</span>
					</p>
					<p v-else class="text-gray-500">No version taken yet.</p>
				</div>

				<FormControl
					v-model="datasetNote"
					label="Note for this version (optional)"
					description="Why you are recording the dataset here — read later beside the version number."
				/>
				<div
					v-if="importPreview"
					class="border border-blue-100 bg-blue-50 rounded-md p-3 text-sm space-y-1"
				>
					<p class="font-medium text-gray-800">
						{{ importFileName }} holds
						{{ importPreview.created.length + importPreview.updated.length }}
						case(s) for this suite.
					</p>
					<p v-if="importPreview.created.length">
						<span class="font-medium">{{ importPreview.created.length }} new:</span>
						{{ importPreview.created.slice(0, 4).join(", ")
						}}<span v-if="importPreview.created.length > 4">, …</span>
					</p>
					<p v-if="importPreview.updated.length">
						<span class="font-medium"
							>{{ importPreview.updated.length }} already here</span
						>, and will be overwritten:
						{{ importPreview.updated.slice(0, 4).join(", ")
						}}<span v-if="importPreview.updated.length > 4">, …</span>
					</p>
					<p v-if="importPreview.left_alone.length" class="text-gray-600">
						{{ importPreview.left_alone.length }} case(s) in this suite are not in the
						file and stay as they are.
					</p>
					<p v-if="importPreview.merged_from.length" class="text-amber-700">
						This file holds cases from {{ importPreview.merged_from.length }} suites
						({{ importPreview.merged_from.join(", ") }}) and they will all land in this
						one.
					</p>
					<p v-if="importPreview.skipped.length" class="text-amber-700">
						{{ importPreview.skipped.length }} entry(ies) have no title and will be
						ignored.
					</p>
				</div>
				<p v-if="datasetMessage" class="text-sm text-green-700">{{ datasetMessage }}</p>
				<p v-if="datasetError" class="text-sm text-red-600">{{ datasetError }}</p>
				<input
					ref="importInput"
					type="file"
					accept="application/json,.json"
					class="hidden"
					@change="previewImport"
				/>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button :loading="datasetBusy" @click="downloadDataset">Export</Button>
				<Button v-if="!importPreview" :loading="datasetBusy" @click="chooseImportFile"
					>Import…</Button
				>
				<Button v-else :loading="datasetBusy" @click="cancelImport">Cancel import</Button>
				<Button
					v-if="importPreview"
					variant="solid"
					theme="blue"
					:loading="datasetBusy"
					@click="applyImport"
					>Import
					{{ importPreview.created.length + importPreview.updated.length }}
					case(s)</Button
				>
				<Button v-else variant="solid" :loading="datasetBusy" @click="takeSnapshot"
					>Take version</Button
				>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { inject } from "vue";
import { Button, Dialog, FormControl } from "frappe-ui";
import { DATASET_SCOPES } from "@/utils/evalLabels";
import { EVAL_SUITE_KEY } from "@/composables/useEvalSuiteState";

const {
	showDataset,
	readiness,
	datasetScope,
	datasetNote,
	datasetBusy,
	datasetMessage,
	datasetError,
	importInput,
	importPreview,
	importFileName,
	loadReadiness,
	takeSnapshot,
	chooseImportFile,
	cancelImport,
	previewImport,
	applyImport,
	downloadDataset,
} = inject(EVAL_SUITE_KEY);
</script>
