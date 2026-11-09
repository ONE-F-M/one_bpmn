<template>
	<div
		v-if="reconciler && reconciler.ok === false"
		class="mx-4 sm:mx-6 mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3"
	>
		<div class="flex items-start gap-3">
			<Icon icon="lucide:clock" class="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
			<div class="min-w-0">
				<p class="text-sm font-medium text-amber-900">
					Delegations may look stuck because nothing is waking them
				</p>
				<p class="text-sm text-amber-800 mt-0.5">{{ reconciler.summary }}</p>
				<p v-if="reconciler.fix" class="text-xs text-amber-700 mt-1">
					{{ reconciler.fix }}
				</p>
				<p class="text-xs text-amber-600 mt-1">
					Last ran
					<template v-if="reconciler.seconds_since_last_run !== null">
						{{ describeAgo(reconciler.seconds_since_last_run) }} ago
					</template>
					<template v-else>never</template>
					· expected every {{ describeAgo(reconciler.interval_seconds) }} · queue “{{
						reconciler.queue
					}}”
					<template v-if="reconciler.queue_depth">
						· {{ reconciler.queue_depth }} job(s) waiting</template
					>
				</p>
			</div>
		</div>
	</div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { Icon } from "@iconify/vue";
import { frappeRequest } from "frappe-ui";
import { A2A_API } from "@/utils/a2aApi";
import { describeAgo } from "@/utils/a2aFormat";

const reconciler = ref(null);

onMounted(async () => {
	try {
		reconciler.value = await frappeRequest({ url: A2A_API + "reconciler_status" });
	} catch {
		// A failed health check hides the banner rather than breaking the page.
		reconciler.value = null;
	}
});
</script>
