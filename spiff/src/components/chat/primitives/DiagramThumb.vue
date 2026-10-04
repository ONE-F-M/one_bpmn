<template>
	<div class="prim-thumb-wrap">
		<div ref="host" class="prim-thumb" :class="{ 'prim-thumb--large': large }">
			<div v-if="!ready" class="prim-thumb-wait">{{ error || "Rendering preview…" }}</div>
		</div>
		<div v-if="large && ready" class="prim-thumb-zoom">
			<button type="button" :title="__('Zoom in')" :aria-label="__('Zoom in')" @click="zoomBy(ZOOM_STEP)">+</button>
			<button type="button" :title="__('Zoom out')" :aria-label="__('Zoom out')" @click="zoomBy(1 / ZOOM_STEP)">−</button>
			<button type="button" :title="__('Fit to window')" :aria-label="__('Fit to window')" @click="fit">⤢</button>
		</div>
	</div>
</template>
<script setup>
// Display primitive (WI-001673): read-only BPMN thumbnail from XML.
// bpmn-js is already a spiff dependency; the viewer is lazy-imported so
// non-diagram conversations never pay for it.
// `height` and `large` let the expanded window reuse it; the defaults keep
// the chat thumbnail as it was.
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
	xml: { type: String, default: "" },
	height: { type: Number, default: 180 },
	// Removes the 190px max-height constraint so the expanded dialog can
	// use the full height passed via `height` instead of being clipped.
	large: { type: Boolean, default: false },
});
const host = ref(null);
const ready = ref(false);
const error = ref("");
let viewer = null;
// Closing the expanded window can unmount this before the lazy import or
// importXML resolves; without the flag that viewer would never be destroyed.
let disposed = false;

const ZOOM_STEP = 1.25;

function fit() {
	viewer?.get("canvas").zoom("fit-viewport", "auto");
}

// Zooms around the centre of the view, so the part being read stays in place.
function zoomBy(factor) {
	const canvas = viewer?.get("canvas");
	if (!canvas) return;
	const { width, height } = canvas.viewbox().outer;
	canvas.zoom(canvas.zoom() * factor, { x: width / 2, y: height / 2 });
}

onMounted(async () => {
	if (!props.xml) {
		error.value = "No diagram";
		return;
	}
	try {
		const { default: NavigatedViewer } = await import("bpmn-js/lib/NavigatedViewer");
		if (disposed) return;
		viewer = new NavigatedViewer({ container: host.value, height: props.height });
		await viewer.importXML(props.xml);
		if (disposed) return;
		// Fit once the freshly opened window has laid out.
		await nextTick();
		const canvas = viewer.get("canvas");
		canvas.resized();
		fit();
		ready.value = true;
	} catch (e) {
		error.value = "Preview unavailable";
	}
});
onBeforeUnmount(() => {
	disposed = true;
	if (viewer) viewer.destroy();
});
</script>
<style scoped>
.prim-thumb { border: 1px solid #e2e2e2; border-radius: 8px; background: #f8f8f8;
	min-height: 120px; max-height: 190px; overflow: hidden; }
.prim-thumb--large { max-height: none; }
.prim-thumb-wrap { position: relative; }
.prim-thumb-zoom { position: absolute; top: 8px; right: 8px; display: flex; flex-direction: column; gap: 4px; }
.prim-thumb-zoom button { width: 28px; height: 28px; padding: 0; border: 1px solid #e2e2e2; border-radius: 6px;
	background: #fff; color: #383838; font-size: 16px; line-height: 1; cursor: pointer; }
.prim-thumb-zoom button:hover { background: #ededed; color: #171717; }
:global([data-theme="dark"]) .prim-thumb-zoom button { border-color: #343434; background: #2a2a2a; color: #d4d4d4; }
.prim-thumb-wait { padding: 24px; text-align: center; color: #999; font-size: 12px; }
:global([data-theme="dark"]) .prim-thumb { border-color: #343434; background: #232323; }
</style>
