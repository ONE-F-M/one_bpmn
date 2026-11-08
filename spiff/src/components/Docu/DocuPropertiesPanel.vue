<template>
	<div v-if="view === 'form'" class="dc-props-panel" :inert="!canChange">
		<template v-if="sel.type === 'field' && sel.node">
			<div class="fb-props-header">
				<div class="fb-props-search">
					<span class="fb-props-search-ico">⌕</span>
					<input v-model="propSearch" type="text" placeholder="Search properties..." />
					<button
						v-if="propSearch"
						class="fb-props-search-x"
						title="Clear"
						@click="propSearch = ''"
					>
						✕
					</button>
				</div>
				<button class="fb-props-close" title="Close properties" @click="selectForm()">
					✕
				</button>
			</div>
			<div class="fb-props-body">
				<template v-for="p in visibleFieldProps" :key="p.key">
					<label v-if="p.type === 'check'" class="fb-prop-check">
						<input v-model="sel.node.df[p.key]" type="checkbox" />
						<span>{{ p.label }}</span>
					</label>
					<div v-else class="dc-prop">
						<label>{{ p.label }}</label>
						<select
							v-if="p.type === 'select'"
							v-model="sel.node.df[p.key]"
							class="dc-prop-input"
						>
							<option v-for="o in p.options" :key="o" :value="o">{{ o }}</option>
						</select>
						<textarea
							v-else-if="p.type === 'textarea' || p.type === 'code'"
							v-model="sel.node.df[p.key]"
							class="dc-prop-input"
							:class="{ 'dc-mono': p.type === 'code' }"
							rows="3"
							:placeholder="p.placeholder || ''"
						></textarea>
						<input
							v-else-if="p.type === 'int'"
							v-model.number="sel.node.df[p.key]"
							type="number"
							class="dc-prop-input"
							:placeholder="p.placeholder || '0'"
						/>
						<input
							v-else
							v-model="sel.node.df[p.key]"
							class="dc-prop-input"
							:class="{ 'dc-mono': p.mono }"
							:placeholder="p.placeholder || ''"
							@blur="p.key === 'label' && autoName(sel.node.df)"
						/>
						<p v-if="p.hint" class="fb-prop-hint">{{ p.hint }}</p>
					</div>
				</template>
				<p v-if="!visibleFieldProps.length" class="dc-hint">
					No properties match “{{ propSearch }}”.
				</p>
				<button class="dc-delete-btn" @click="deleteSelected()">Delete field</button>
			</div>
		</template>

		<template
			v-else-if="
				(sel.type === 'section' || sel.type === 'column' || sel.type === 'tab') && sel.node
			"
		>
			<div class="dc-props-head">{{ capitalize(sel.type) }} properties</div>
			<div class="dc-prop">
				<label>Label</label>
				<input
					v-model="sel.node.df.label"
					class="dc-prop-input"
					:placeholder="sel.type + ' title (optional)'"
				/>
			</div>
			<div v-if="sel.type !== 'column'" class="dc-prop">
				<label>Description</label>
				<input v-model="sel.node.df.description" class="dc-prop-input" />
			</div>
			<label v-if="sel.type === 'section'" class="dc-switch">
				<input v-model="sel.node.df.collapsible" type="checkbox" />
				<span class="dc-switch-track"><span class="dc-switch-thumb"></span></span>
				<span class="dc-switch-text">Collapsible section</span>
			</label>
			<p class="dc-hint">
				Drag {{ sel.type === "tab" ? "tabs" : sel.type + "s" }} to rearrange. Fields drag
				between columns.
			</p>
			<button class="dc-delete-btn" @click="deleteSelected()">Delete {{ sel.type }}</button>
		</template>

		<template v-else>
			<div class="dc-props-head">Properties</div>
			<p class="dc-hint">
				Select a field, section, column or tab to edit its properties. Ask Docu on the left
				to build or change the DocType, then drag to arrange. DocType-wide settings live in
				the <strong>Settings</strong> tab.
			</p>
		</template>
	</div>
</template>

<script setup>
import { computed, ref } from "vue";
import { fieldPropDefs } from "@/utils/docuFieldDefs";
import { capitalize } from "@/utils/docuFieldDefs";
import { useDocu } from "@/composables/useDocu";

const { view, sel, selectForm, autoName, deleteSelected, canChange } = useDocu();

const propSearch = ref("");

const visibleFieldProps = computed(() => {
	if (sel.type !== "field" || !sel.node) return [];
	const q = propSearch.value.trim().toLowerCase();
	return fieldPropDefs(sel.node.df).filter((p) => {
		if (p.show === false) return false;
		if (q && !(p.label.toLowerCase().includes(q) || p.key.toLowerCase().includes(q)))
			return false;
		return true;
	});
});
</script>

<style scoped src="@/components/Docu/docuPropertiesPanel.css"></style>
