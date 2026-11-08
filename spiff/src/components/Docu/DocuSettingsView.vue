<template>
	<div class="dc-settings-page">
		<div class="dc-settings-card">
			<div class="dc-settings-section">
				<div class="dc-settings-grid">
					<div class="dc-prop">
						<label>DocType name</label>
						<input
							v-model="dtName"
							class="dc-prop-input"
							placeholder="e.g. Vehicle Inspection"
						/>
					</div>
					<div class="dc-prop">
						<label>Module</label>
						<select v-model="dtModule" class="dc-prop-input">
							<option v-for="m in moduleOptions" :key="m" :value="m">{{ m }}</option>
						</select>
					</div>
					<div class="dc-prop">
						<label>Auto Name</label>
						<input
							v-model="dtAutoname"
							class="dc-prop-input dc-mono"
							placeholder="e.g. field:vehicle_no or format:VI-.#####"
						/>
					</div>
					<div class="dc-prop">
						<label>Description</label>
						<textarea
							v-model="dtSettings.description"
							class="dc-prop-input"
							rows="2"
						></textarea>
					</div>
					<label class="fb-prop-check">
						<input v-model="isChild" type="checkbox" />
						<span>Is Child Table (lives inside another DocType)</span>
					</label>
				</div>
			</div>

			<div v-for="sec in settingsSections" :key="sec.title" class="dc-settings-section">
				<div class="dc-settings-title">{{ sec.title }}</div>
				<div class="dc-settings-grid">
					<template v-for="f in sec.fields" :key="f.key">
						<label v-if="f.type === 'check'" class="fb-prop-check">
							<input v-model="dtSettings[f.key]" type="checkbox" />
							<span>{{ f.label }}</span>
						</label>
						<div v-else class="dc-prop">
							<label>{{ f.label }}</label>
							<select
								v-if="f.type === 'select'"
								v-model="dtSettings[f.key]"
								class="dc-prop-input"
							>
								<option v-for="o in f.options" :key="o" :value="o">
									{{ o || "—" }}
								</option>
							</select>
							<input
								v-else-if="f.type === 'int'"
								v-model.number="dtSettings[f.key]"
								type="number"
								class="dc-prop-input"
								placeholder="0"
							/>
							<input
								v-else
								v-model="dtSettings[f.key]"
								class="dc-prop-input"
								:placeholder="f.placeholder || ''"
							/>
						</div>
					</template>
				</div>
			</div>

			<DocuPermissionRules v-if="!isChild" />

			<p class="dc-hint">
				These settings apply to the whole DocType. Switch to the <strong>Form</strong> tab
				to design its fields.
			</p>
		</div>
	</div>
</template>

<script setup>
import DocuPermissionRules from "@/components/Docu/DocuPermissionRules.vue";
import { useDocu } from "@/composables/useDocu";

const { dtName, dtModule, dtAutoname, isChild, dtSettings, moduleOptions, settingsSections } =
	useDocu();
</script>

<style scoped src="@/components/Docu/docuSettingsView.css"></style>
