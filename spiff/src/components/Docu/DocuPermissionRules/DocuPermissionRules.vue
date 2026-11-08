<template>
	<div class="dc-settings-section">
		<div class="dc-settings-title">Permission Rules</div>
		<div class="dc-perm-scroll">
			<table class="dc-perm-table">
				<thead>
					<tr>
						<th class="dc-perm-no">No.</th>
						<th class="dc-perm-role">Role</th>
						<th class="dc-perm-lvl">Level</th>
						<th v-for="c in PERMISSION_COLUMNS" :key="c.key">{{ c.label }}</th>
						<th class="dc-perm-x"><span class="sr-only">Remove</span></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(p, i) in permissions" :key="i">
						<td class="dc-perm-no">{{ i + 1 }}</td>
						<td class="dc-perm-role">
							<select
								v-model="p.role"
								class="dc-prop-input"
								:aria-label="`Role for rule ${i + 1}`"
								@change="scheduleAutosave()"
							>
								<option value="">Select a role…</option>
								<option v-for="r in roleOptions(p.role)" :key="r" :value="r">
									{{ r }}
								</option>
							</select>
						</td>
						<td class="dc-perm-lvl">
							<input
								v-model.number="p.permlevel"
								type="number"
								min="0"
								max="9"
								class="dc-prop-input"
								:aria-label="`Level for rule ${i + 1}`"
								@change="scheduleAutosave()"
							/>
						</td>
						<td v-for="c in PERMISSION_COLUMNS" :key="c.key" class="dc-perm-check">
							<input
								type="checkbox"
								:checked="!!p[c.key]"
								:aria-label="`${c.label} for rule ${i + 1}`"
								@change="
									p[c.key] = $event.target.checked ? 1 : 0;
									scheduleAutosave();
								"
							/>
						</td>
						<td class="dc-perm-x">
							<button
								class="dc-perm-remove"
								:title="`Remove rule ${i + 1}`"
								@click="removePermission(i)"
							>
								✕
							</button>
						</td>
					</tr>
					<tr v-if="!permissions.length">
						<td :colspan="PERMISSION_COLUMNS.length + 4" class="dc-perm-empty">
							No rules yet. Without one, only System Manager can open this form.
						</td>
					</tr>
				</tbody>
			</table>
		</div>
		<button class="dc-perm-add" @click="addPermission()">Add Row</button>
	</div>
</template>

<script setup>
import { PERMISSION_COLUMNS } from "@/utils/docuSettingsDefs";
import { useDocu } from "@/composables/useDocu";

const { permissions, roleOptions, addPermission, removePermission, scheduleAutosave } = useDocu();
</script>

<style scoped src="./DocuPermissionRules.css"></style>
