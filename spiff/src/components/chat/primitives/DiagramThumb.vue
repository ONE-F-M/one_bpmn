<template>
	<div ref="host" class="prim-thumb" :class="{ 'prim-thumb--large': large }">
		<div v-if="!ready" class="prim-thumb-wait">{{ error || "Rendering preview…" }}</div>
	</div>
</template>
<script setup>
// Display primitive (WI-001673): read-only BPMN thumbnail from XML.
// bpmn-js is already a spiff dependency; the viewer is lazy-imported so
// non-diagram conversations never pay for it.
//
// WI-003115/WI-003116: height and large let a host (the CardShell #expanded
// dialog) reuse this same viewer at a bigger size instead of building a
// second one — the defaults keep the docked thumbnail exactly as it was.
import { onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
	xml: { type: String, default: "" },
	height: { type: Number, default: 180 },
	large: { type: Boolean, default: false },
});
const host = ref(null);
const ready = ref(false);
const error = ref("");
let viewer = null;

onMounted(async () => {
	if (!props.xml) {
		error.value = "No diagram";
		return;
	}
	try {
		const { default: NavigatedViewer } = await import("bpmn-js/lib/NavigatedViewer");
		viewer = new NavigatedViewer({ container: host.value, height: props.height });
		await viewer.importXML(props.xml);
		viewer.get("canvas").zoom("fit-viewport", "auto");
		ready.value = true;
	} catch (e) {
		error.value = "Preview unavailable";
	}
});
onBeforeUnmount(() => viewer && viewer.destroy());
</script>
<style scoped>
.prim-thumb { border: 1px solid #e2e2e2; border-radius: 8px; background: #f8f8f8;
	min-height: 120px; max-height: 190px; overflow: hidden; }
.prim-thumb--large { max-height: none; }
.prim-thumb-wait { padding: 24px; text-align: center; color: #999; font-size: 12px; }
:global([data-theme="dark"]) .prim-thumb { border-color: #343434; background: #232323; }
</style>
