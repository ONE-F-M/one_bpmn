// WI-001678: builds the one-ai desk bundle — a self-contained IIFE (Vue
// bundled) mounted by the one-ai Desk page and the WI-001996 Chat button
// loader. Separate from the SPA build on purpose: Desk must not pay for the
// modeler, and the SPA must not pay for a second Vue copy.
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import Icons from "unplugin-icons/vite";
import path from "path";

export default defineConfig({
	// frappe-ui's components import ~icons/* virtual modules; the SPA build
	// gets this via frappeui({ lucideIcons: true }) — the lib build needs the
	// underlying plugin directly (autoInstall off: iconify sets are in deps).
	plugins: [vue(), Icons({ compiler: "vue3" })],
	resolve: { alias: { "@": path.resolve(__dirname, "src") } },
	define: { "process.env.NODE_ENV": JSON.stringify("production") },
	build: {
		lib: {
			entry: path.resolve(__dirname, "src/oneai-entry.js"),
			name: "oneAI",
			formats: ["iife"],
			fileName: () => "one-ai.iife.js",
		},
		outDir: "../one_bpmn/public/one_ai",
		emptyOutDir: true,
		rollupOptions: { output: { assetFileNames: "one-ai.[ext]" } },
	},
});
