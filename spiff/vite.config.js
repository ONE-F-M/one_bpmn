import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import path from "path"
import { defineConfig } from "vite"

export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,
			lucideIcons: true,
			jinjaBootData: true,
			buildConfig: {
				outDir: `../one_bpmn/public/processa`,
				emptyOutDir: true,
				indexHtmlPath: "../one_bpmn/www/processa/index.html",
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
			"preact/hooks": path.resolve(__dirname, "node_modules/preact/hooks"),
			"preact": path.resolve(__dirname, "node_modules/preact"),
		},
		// Both bpmn-js-properties-panel and bpmn-js-spiffworkflow depend on
		// @bpmn-io/properties-panel, which ships a bundled Preact copy that its
		// dist imports via relative paths (../preact/hooks). Without dedupe,
		// Rollup resolves the nested copy inside bpmn-js-spiffworkflow/node_modules
		// separately from the top-level copy, producing TWO Preact instances and
		// crashing with "Cannot read properties of undefined (reading '__H')".
		// Deduplicating @bpmn-io/properties-panel forces a single copy (and
		// therefore a single bundled Preact) across the entire build.
		dedupe: [
			"@bpmn-io/properties-panel",
			"preact",
			"preact/hooks",
			"preact/compat",
		],
	},
	optimizeDeps: {
		include: [
			"feather-icons",
			"bpmnlint",
			"bpmnlint-utils",
		],
	},
	build: {
		sourcemap: false,
		chunkSizeWarningLimit: 1500,
	},
})

