<template>
	<div class="dt-card">
		<DataTable
			:title="value.title"
			:columns="value.columns"
			:rows="value.rows"
			:row-action="value.row_action"
			@row-action="(action, row) => $emit('action', action, row)"
		/>
		<button
			v-if="value.rows && value.rows.length"
			class="dt-card-expand"
			type="button"
			:title="__('Open in larger window')"
			@click="open = true"
		>
			<Icon icon="lucide:maximize-2" class="dt-card-expand-icon" />
		</button>

		<Dialog v-if="value.rows && value.rows.length" v-model="open" :options="{ title: value.title || __('Table'), size: '7xl' }">
			<template #body-content>
				<div class="h-[75vh] overflow-auto">
					<!-- #expanded: same table, full width, no row-action — the
					     dialog is a read-only preview. -->
					<slot v-if="open" name="expanded">
						<DataTable class="w-full" :columns="value.columns" :rows="value.rows" />
					</slot>
				</div>
			</template>
		</Dialog>
	</div>
</template>
<script setup>
// onefm.table binds the DataTable primitive directly — no CardShell, per
// the contract note: it is data, not a proposal awaiting a decision.
//
// WI-003115: since this card has no CardShell, it carries its own expand
// button and Dialog, wired the same way: an #expanded slot (default content
// is the same DataTable, full width, without the row-action column) so a
// consumer could still override it. Explicit Dialog import — the one-ai IIFE
// bundle never runs main.js, so nothing registers Dialog globally there.
import { ref } from "vue";
import { Icon } from "@iconify/vue";
import { Dialog } from "frappe-ui";
import DataTable from "../primitives/DataTable.vue";

const __ = (window.__ && typeof window.__ === "function") ? window.__ : (s) => s;

defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
	done: { type: Boolean, default: false },
});
defineEmits(["action"]);

const open = ref(false);
</script>
<style scoped>
.dt-card { position: relative; align-self: flex-start; width: 94%; background: #fff; border: 1px solid #e2e2e2;
	border-radius: 10px; padding: 10px 12px; }
.dt-card-expand { position: absolute; top: 8px; right: 8px; display: grid; place-items: center; width: 22px;
	height: 22px; border-radius: 6px; border: none; background: transparent; color: #7c7c7c; cursor: pointer; }
.dt-card-expand:hover { background: #ededed; color: #171717; }
.dt-card-expand-icon { width: 14px; height: 14px; }
:global([data-theme="dark"]) .dt-card { background: #1c1c1c; border-color: #343434; }
:global([data-theme="dark"]) .dt-card-expand { color: #999; }
:global([data-theme="dark"]) .dt-card-expand:hover { background: #343434; color: #f8f8f8; }
</style>
