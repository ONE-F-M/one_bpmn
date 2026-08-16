<template>
	<div class="prim-choices">
		<ActionButton
			v-for="opt in options"
			:key="opt"
			:label="opt"
			:kind="picked === opt ? 'solid' : 'subtle'"
			:disabled="disabled || !!picked"
			@press="pick(opt)"
		/>
	</div>
</template>
<script setup>
// Interactive primitive (WI-001673): the onefm.choice option row.
import { ref } from "vue";
import ActionButton from "./ActionButton.vue";
defineProps({ options: { type: Array, default: () => [] }, disabled: { type: Boolean, default: false } });
const emit = defineEmits(["pick"]);
const picked = ref("");
function pick(opt) { picked.value = opt; emit("pick", opt); }
</script>
<style scoped>
.prim-choices { display: flex; gap: 8px; flex-wrap: wrap; }
</style>
