<script setup>
import { inject } from "vue";
import DocuCanvas from "@/components/Docu/DocuCanvas/DocuCanvas.vue";
import { EDITOR_KEY } from "@/composables/useEditorState";

const ed = inject(EDITOR_KEY);
const { docuPanel, docuProcessContext, onDocuApplied } = ed;
</script>

<template>
	<!-- Docu - AI DocType builder -->
	<DocuCanvas
		v-if="docuPanel.element"
		:key="`${docuPanel.element.id}:${docuPanel.attr}`"
		:open="docuPanel.show"
		:element="docuPanel.element"
		:doctype="docuPanel.doctype"
		:attr="docuPanel.attr"
		:process-context="docuProcessContext"
		@applied="onDocuApplied"
		@close="docuPanel.show = false"
	/>
</template>
