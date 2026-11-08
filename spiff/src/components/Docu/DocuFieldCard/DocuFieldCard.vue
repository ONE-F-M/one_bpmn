<template>
	<div
		class="fb-field"
		:class="{ selected: isSelField(fld) }"
		:title="fld.df.fieldname || fld.df.label"
		@click.stop="selectField(fld)"
	>
		<div class="control frappe-control editable">
			<div class="field-controls">
				<div class="field-label">
					<span class="fb-flabel" :class="{ empty: !fld.df.label }">
						{{ fld.df.label || "No Label (" + fld.df.fieldtype + ")" }}
					</span>
					<span v-if="fld.df.reqd" class="reqd-asterisk">*</span>
				</div>
				<div class="field-actions">
					<button
						class="fb-icon"
						title="Add field below"
						@click.stop="addFieldAfter(column, fld)"
					>
						<svg viewBox="0 0 16 16" aria-hidden="true">
							<path d="M8 3.5v9M3.5 8h9" />
						</svg>
					</button>
					<button
						v-if="column.fields.indexOf(fld) > 0"
						class="fb-icon"
						title="Move this and the following fields to a new column"
						@click.stop="moveFieldsToNewColumn(column, fld)"
					>
						<svg viewBox="0 0 16 16" aria-hidden="true">
							<path d="M6 10.5 10.5 6M7 5.5h4v4" />
						</svg>
					</button>
					<button
						class="fb-icon"
						title="Duplicate field"
						@click.stop="duplicateField(column, fld)"
					>
						<svg viewBox="0 0 16 16" aria-hidden="true">
							<rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.3" />
							<path
								d="M10.5 5.5V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v5.5a1 1 0 0 0 1 1h1.5"
							/>
						</svg>
					</button>
					<button
						class="fb-icon"
						title="Remove field"
						@click.stop="removeField(column, fld)"
					>
						<svg viewBox="0 0 16 16" aria-hidden="true">
							<path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5" />
						</svg>
					</button>
				</div>
			</div>
			<label v-if="previewKind(fld.df.fieldtype) === 'check'" class="fb-check">
				<input type="checkbox" disabled />
			</label>
			<select
				v-else-if="previewKind(fld.df.fieldtype) === 'select'"
				class="form-control"
				disabled
			>
				<option>{{ (fld.df.options || "").split("\n")[0] || "" }}</option>
			</select>
			<textarea
				v-else-if="previewKind(fld.df.fieldtype) === 'textarea'"
				class="form-control"
				rows="2"
				readonly
			></textarea>
			<div v-else-if="previewKind(fld.df.fieldtype) === 'table'" class="fb-table-preview">
				▦ {{ fld.df.options || "child table" }}
			</div>
			<div
				v-else-if="previewKind(fld.df.fieldtype) === 'heading'"
				class="fb-heading-preview"
			>
				{{ fld.df.label }}
			</div>
			<div v-else-if="previewKind(fld.df.fieldtype) === 'html'" class="fb-html-preview">
				HTML
			</div>
			<input
				v-else
				class="form-control"
				type="text"
				readonly
				:placeholder="previewPlaceholder(fld.df)"
			/>
		</div>
	</div>
</template>

<script setup>
import { previewKind, previewPlaceholder } from "@/utils/docuFieldDefs";
import { useDocu } from "@/composables/useDocu";

const {
	selectField,
	isSelField,
	removeField,
	duplicateField,
	addFieldAfter,
	moveFieldsToNewColumn,
} = useDocu();

defineProps({
	fld: { type: Object, required: true },
	column: { type: Object, required: true },
});
</script>

<style scoped src="./DocuFieldCard.css"></style>
