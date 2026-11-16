import js from "@eslint/js"
import prettier from "eslint-config-prettier"
import pluginVue from "eslint-plugin-vue"
import globals from "globals"

export default [
	{ ignores: ["node_modules/**", "dist/**", "auto-imports.d.ts", "components.d.ts"] },
	js.configs.recommended,
	...pluginVue.configs["flat/recommended"],
	{
		languageOptions: {
			ecmaVersion: "latest",
			sourceType: "module",
			globals: { ...globals.browser, ...globals.node },
		},
		rules: {
			"vue/multi-word-component-names": "off",
		},
	},
	prettier,
]
