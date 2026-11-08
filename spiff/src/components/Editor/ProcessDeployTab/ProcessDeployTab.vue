<script setup>
import { inject } from "vue";
import { Icon } from "@iconify/vue";
import ReadinessChecklistDialog from "@/components/Modals/ReadinessChecklistModal.vue";
import { PROCESS_KEY } from "@/composables/useProcessState";

const pc = inject(PROCESS_KEY);
const {
	closeReview,
	confirmReview,
	disableRunningCount,
	disabling,
	executeDisable,
	executeNonExecutableToggle,
	nonExecutableActivating,
	nonExecutableBusy,
	onReadinessCancel,
	onReadinessClose,
	onReadinessDeploy,
	onReadinessRecheck,
	onReadinessUpdateRefs,
	onReadinessUploadConfig,
	prBaseBranch,
	readinessChecklist,
	readinessLoading,
	readinessMode,
	reviewChanges,
	reviewEmptyMessage,
	reviewIntro,
	reviewKind,
	reviewResult,
	reviewStage,
	reviewTitle,
	runSync,
	showDisableDialog,
	showNonExecutableDialog,
	showReadinessDialog,
	showReviewDialog,
	syncingLabel,
} = pc;
</script>

<template>
	<!-- Readiness Checklist Dialog (import & deploy) -->
	<ReadinessChecklistDialog
		v-model="showReadinessDialog"
		:checklist="readinessChecklist"
		:mode="readinessMode"
		:loading="readinessLoading"
		@close="onReadinessClose"
		@cancel="onReadinessCancel"
		@deploy="onReadinessDeploy"
		@upload-config="onReadinessUploadConfig"
		@recheck="onReadinessRecheck"
		@update-refs="onReadinessUpdateRefs"
	/>

	<!-- Disable Process Confirmation Dialog -->
	<Dialog v-model="showDisableDialog" :options="{ title: 'Disable Process Map', size: 'sm' }">
		<template #body-content>
			<div class="space-y-3">
				<div
					class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm border border-orange-200 bg-orange-50 text-orange-800"
				>
					<Icon icon="lucide:alert-triangle" class="w-5 h-5 shrink-0 mt-0.5" />
					<div>
						<div class="font-semibold">
							This will stop all new instances from being created.
						</div>
						<div class="mt-1 opacity-90">
							Linked server scripts will be disabled. You can re-deploy at any time
							to reactivate.
						</div>
					</div>
				</div>
				<div
					v-if="disableRunningCount > 0"
					class="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm border border-blue-200 bg-blue-50 text-blue-800"
				>
					<Icon icon="lucide:info" class="w-4 h-4 shrink-0" />
					<span
						><strong>{{ disableRunningCount }}</strong> running instance(s) will
						continue to completion.</span
					>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2 justify-end w-full">
				<Button variant="subtle" @click="showDisableDialog = false">Cancel</Button>
				<Button variant="solid" theme="red" :loading="disabling" @click="executeDisable"
					>Disable</Button
				>
			</div>
		</template>
	</Dialog>

	<!-- Non-executable process Deploy / Disable confirmation -->
	<Dialog
		v-model="showNonExecutableDialog"
		:options="{
			title: nonExecutableActivating ? 'Deploy Process Model' : 'Disable Process Model',
			size: 'sm',
		}"
	>
		<template #body-content>
			<div class="text-sm text-gray-700">
				{{
					nonExecutableActivating
						? "This is a non-executable process mode, process instances will not be created. Any other process model for this process will become inactive."
						: "This will mark this process as inactive."
				}}
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2 justify-end w-full">
				<Button variant="subtle" @click="showNonExecutableDialog = false">Cancel</Button>
				<Button
					variant="solid"
					:theme="nonExecutableActivating ? 'gray' : 'red'"
					:loading="nonExecutableBusy"
					@click="executeNonExecutableToggle"
				>
					{{ nonExecutableActivating ? "Deploy" : "Disable" }}
				</Button>
			</div>
		</template>
	</Dialog>

	<!-- Production Review dialog (Review Doctypes / Review Workflow Objects) -->
	<Dialog v-model="showReviewDialog" :options="{ title: reviewTitle, size: 'xl' }">
		<template #body-content>
			<!-- Intro / confirmation -->
			<div v-if="reviewStage === 'intro'" class="text-sm text-gray-700 leading-relaxed">
				{{ reviewIntro }}
			</div>

			<!-- Comparing -->
			<div
				v-else-if="reviewStage === 'loading'"
				class="flex items-center gap-3 py-6 text-sm text-gray-600"
			>
				<Icon icon="lucide:loader-2" class="w-5 h-5 animate-spin" />
				Comparing with Production…
			</div>

			<!-- Diffs -->
			<div v-else-if="reviewStage === 'diff'" class="space-y-3">
				<p class="text-sm text-gray-600">
					{{ reviewChanges.length }} change(s) found between this site and Production.
				</p>
				<div class="max-h-80 overflow-auto border border-gray-200 rounded-lg">
					<table class="w-full text-sm">
						<thead class="bg-gray-50 text-gray-500 text-xs uppercase sticky top-0">
							<tr>
								<th class="text-left px-3 py-2 font-medium">Object</th>
								<th class="text-left px-3 py-2 font-medium">Name</th>
								<th class="text-left px-3 py-2 font-medium">Action</th>
								<th class="text-left px-3 py-2 font-medium">Changed</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="(c, i) in reviewChanges"
								:key="i"
								class="border-t border-gray-100"
							>
								<td class="px-3 py-2 text-gray-700 whitespace-nowrap">
									{{ c.object_type }}
								</td>
								<td class="px-3 py-2 text-gray-800 font-medium">
									{{ c.name }}
									<span
										v-if="c.doctype && c.doctype !== c.name"
										class="text-gray-400"
										>· {{ c.doctype }}</span
									>
									<!-- We own this DocType, so Sync edits its own JSON rather than
								     minting an override - name the file it lands in. -->
									<div
										v-if="c.destination"
										class="text-[11px] text-gray-400 font-normal font-mono"
									>
										{{ c.destination }}
									</div>
								</td>
								<td class="px-3 py-2">
									<span
										:class="
											c.action === 'Create'
												? 'text-green-600'
												: 'text-amber-600'
										"
										>{{ c.action }}</span
									>
								</td>
								<td class="px-3 py-2 text-gray-500 text-xs">{{ c.detail }}</td>
							</tr>
						</tbody>
					</table>
				</div>
				<p v-if="reviewKind === 'doctypes'" class="text-xs text-gray-500">
					Sync opens a GitHub pull request against {{ prBaseBranch }} (per owning app)
					with these changes. Merging and deploying migrates Production.
				</p>
				<p v-else class="text-xs text-gray-500">
					Sync overwrites existing records and creates new ones on the linked Production
					system.
				</p>
			</div>

			<!-- No differences -->
			<div
				v-else-if="reviewStage === 'empty'"
				class="flex items-center gap-3 py-4 text-sm text-gray-700"
			>
				<Icon icon="lucide:check-circle-2" class="w-5 h-5 text-green-600" />
				{{ reviewEmptyMessage }}
			</div>

			<!-- Syncing -->
			<div
				v-else-if="reviewStage === 'syncing'"
				class="flex items-center gap-3 py-6 text-sm text-gray-600"
			>
				<Icon icon="lucide:loader-2" class="w-5 h-5 animate-spin" />
				{{ syncingLabel }}
			</div>

			<!-- Sync result -->
			<div v-else-if="reviewStage === 'result'" class="space-y-3 text-sm">
				<div
					v-if="reviewResult && reviewResult.error"
					class="flex items-start gap-3 rounded-lg px-4 py-3 border border-red-200 bg-red-50 text-red-800"
				>
					<Icon icon="lucide:alert-circle" class="w-5 h-5 shrink-0 mt-0.5" />
					<div class="whitespace-pre-wrap">{{ reviewResult.error }}</div>
				</div>
				<template v-else-if="reviewKind === 'doctypes'">
					<div
						v-if="reviewResult && reviewResult.prs && reviewResult.prs.length"
						class="space-y-2"
					>
						<div class="text-gray-700">
							Pull request(s) opened against {{ prBaseBranch }}:
						</div>
						<a
							v-for="(pr, i) in reviewResult.prs"
							:key="i"
							:href="pr.pr_url"
							target="_blank"
							class="flex items-center gap-2 text-blue-600 hover:underline"
						>
							<Icon icon="lucide:git-pull-request" class="w-4 h-4" />
							{{ pr.repository }} — {{ (pr.doctypes || []).join(", ") }}
							<span v-if="pr.files && pr.files.length" class="text-gray-500 text-sm"
								>({{ pr.files.length }} files)</span
							>
						</a>
					</div>
					<div
						v-for="(s, i) in (reviewResult && reviewResult.skipped) || []"
						:key="'s' + i"
						class="flex items-start gap-2 rounded-lg px-3 py-2 border border-amber-200 bg-amber-50 text-amber-800"
					>
						<Icon icon="lucide:alert-triangle" class="w-4 h-4 shrink-0 mt-0.5" />
						<span>{{ s.reason }} ({{ (s.doctypes || []).join(", ") }})</span>
					</div>
				</template>
				<template v-else>
					<div
						class="flex items-start gap-3 rounded-lg px-4 py-3 border border-green-200 bg-green-50 text-green-800"
					>
						<Icon icon="lucide:check-circle-2" class="w-5 h-5 shrink-0 mt-0.5" />
						<div>
							<div class="font-semibold">Synced to Production.</div>
							<div
								v-if="reviewResult && reviewResult.results"
								class="mt-1 opacity-90"
							>
								{{ (reviewResult.results.created || []).length }} created,
								{{ (reviewResult.results.updated || []).length }} updated<span
									v-if="(reviewResult.results.failed || []).length"
									>, {{ reviewResult.results.failed.length }} failed</span
								>.
							</div>
						</div>
					</div>
					<div
						v-for="(f, i) in (reviewResult &&
							reviewResult.results &&
							reviewResult.results.failed) ||
						[]"
						:key="'f' + i"
						class="text-xs text-red-600"
					>
						{{ f }}
					</div>
				</template>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2 justify-end w-full">
				<template v-if="reviewStage === 'intro'">
					<Button variant="subtle" @click="closeReview">Cancel</Button>
					<Button variant="solid" @click="confirmReview">Confirm</Button>
				</template>
				<template v-else-if="reviewStage === 'diff'">
					<Button variant="subtle" @click="closeReview">Close</Button>
					<Button variant="solid" theme="blue" @click="runSync">Sync</Button>
				</template>
				<template v-else-if="reviewStage === 'empty' || reviewStage === 'result'">
					<Button variant="solid" @click="closeReview">Close</Button>
				</template>
			</div>
		</template>
	</Dialog>
</template>
