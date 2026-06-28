<template>
	<div ref="editorEl" class="cm-editor-wrap"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { EditorView, keymap, placeholder as cmPlaceholder, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { defaultKeymap, indentWithTab, history, historyKeymap } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle, indentOnInput, bracketMatching, foldGutter, foldKeymap, HighlightStyle } from "@codemirror/language";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { tags } from "@lezer/highlight";

const props = defineProps({
	modelValue:  { type: String,  default: "" },
	language:    { type: String,  default: "python" },
	readOnly:    { type: Boolean, default: false },
	placeholder: { type: String,  default: "" },
});

const emit = defineEmits(["update:modelValue", "change"]);

const editorEl = ref(null);
let view = null;
let ignoreNextUpdate = false;
const readOnlyCompartment = new Compartment();

// ── Light theme (matches the LogixCanvas aesthetic) ───────────────────
const logixLightTheme = EditorView.theme({
	"&": {
		fontFamily: "\"JetBrains Mono\", \"Fira Code\", \"Cascadia Code\", monospace",
		fontSize: "12.5px",
		lineHeight: "1.55",
		backgroundColor: "#fafafa",
		color: "#1c1b1f",
		flex: "1",
		height: "100%",
	},
	".cm-content": {
		padding: "14px 4px",
		caretColor: "#6c3fe0",
	},
	".cm-cursor, .cm-dropCursor": {
		borderLeftColor: "#6c3fe0",
	},
	".cm-gutters": {
		backgroundColor: "#f0f0f0",
		color: "#999",
		borderRight: "1px solid #e0e0e0",
		fontFamily: "\"JetBrains Mono\", \"Fira Code\", monospace",
		fontSize: "12px",
	},
	".cm-lineNumbers .cm-gutterElement": {
		padding: "0 8px 0 4px",
		minWidth: "32px",
	},
	".cm-activeLineGutter": {
		backgroundColor: "#e8e4f0",
		color: "#6c3fe0",
	},
	".cm-activeLine": {
		backgroundColor: "rgba(108, 63, 224, 0.04)",
	},
	".cm-selectionBackground, ::selection": {
		backgroundColor: "rgba(108, 63, 224, 0.15) !important",
	},
	".cm-matchingBracket": {
		backgroundColor: "rgba(108, 63, 224, 0.2)",
		outline: "1px solid rgba(108, 63, 224, 0.4)",
	},
	".cm-foldGutter .cm-gutterElement": {
		padding: "0 2px",
		cursor: "pointer",
		color: "#bbb",
	},
	".cm-foldGutter .cm-gutterElement:hover": {
		color: "#6c3fe0",
	},
	".cm-foldPlaceholder": {
		backgroundColor: "#f0ebff",
		border: "1px solid #d4c8f0",
		borderRadius: "3px",
		color: "#6c3fe0",
		padding: "0 4px",
		margin: "0 2px",
	},
	"&.cm-focused": {
		outline: "none",
	},
	".cm-scroller": {
		overflow: "auto",
	},
	".cm-placeholder": {
		color: "#bbb",
		fontStyle: "italic",
	},
}, { dark: false });

// ── Syntax highlighting colors (VS Code Light+ theme) ─────────────────
// Uses bold, vivid, clearly-differentiated colors for each token type
const logixHighlightStyle = HighlightStyle.define([
	// ── Keywords (blue, bold — immediately recognizable) ──────────────
	{ tag: tags.keyword,           color: "#0000FF", fontWeight: "bold" },
	{ tag: tags.controlKeyword,    color: "#AF00DB", fontWeight: "bold" }, // if, elif, else, for, while, try, except
	{ tag: tags.moduleKeyword,     color: "#AF00DB", fontWeight: "bold" }, // import, from
	{ tag: tags.operatorKeyword,   color: "#0000FF", fontWeight: "bold" }, // and, or, not, in, is
	{ tag: tags.definitionKeyword, color: "#0000FF", fontWeight: "bold" }, // def, class

	// ── Built-in constants (blue) ─────────────────────────────────────
	{ tag: tags.bool,              color: "#0000FF", fontWeight: "bold" }, // True, False
	{ tag: tags.null,              color: "#0000FF", fontWeight: "bold" }, // None
	{ tag: tags.self,              color: "#0000FF", fontWeight: "bold" }, // self

	// ── Strings (dark red — high contrast) ────────────────────────────
	{ tag: tags.string,                     color: "#A31515" },
	{ tag: tags.special(tags.string),       color: "#A31515" },  // f-strings

	// ── Comments (green, italic — clearly distinct) ───────────────────
	{ tag: tags.comment,           color: "#008000", fontStyle: "italic" },
	{ tag: tags.lineComment,       color: "#008000", fontStyle: "italic" },
	{ tag: tags.blockComment,      color: "#008000", fontStyle: "italic" },

	// ── Numbers (teal green) ──────────────────────────────────────────
	{ tag: tags.number,            color: "#098658" },
	{ tag: tags.integer,           color: "#098658" },
	{ tag: tags.float,             color: "#098658" },

	// ── Functions (brown/gold — function calls and definitions) ───────
	{ tag: tags.function(tags.variableName),                     color: "#795E26" },
	{ tag: tags.function(tags.definition(tags.variableName)),    color: "#795E26", fontWeight: "bold" },
	{ tag: tags.function(tags.propertyName),                     color: "#795E26" }, // method calls like obj.method()

	// ── Definitions (orange — variable definitions) ───────────────────
	{ tag: tags.definition(tags.variableName), color: "#001080" },

	// ── Classes and types (teal) ──────────────────────────────────────
	{ tag: tags.className,                  color: "#267F99" },
	{ tag: tags.definition(tags.className), color: "#267F99", fontWeight: "bold" },
	{ tag: tags.typeName,                   color: "#267F99" },

	// ── Properties and attributes (dark blue) ─────────────────────────
	{ tag: tags.propertyName,      color: "#001080" },
	{ tag: tags.attributeName,     color: "#001080" },

	// ── Variables (dark gray — readable but neutral) ──────────────────
	{ tag: tags.variableName,      color: "#001080" },

	// ── Operators (dark red — visually distinct) ──────────────────────
	{ tag: tags.operator,          color: "#d73a49" },
	{ tag: tags.compareOperator,   color: "#d73a49" },
	{ tag: tags.arithmeticOperator, color: "#d73a49" },
	{ tag: tags.logicOperator,     color: "#d73a49" },

	// ── Decorators (purple) ───────────────────────────────────────────
	{ tag: tags.meta,              color: "#AF00DB" },

	// ── Brackets and punctuation (dark gray) ──────────────────────────
	{ tag: tags.bracket,           color: "#333333" },
	{ tag: tags.squareBracket,     color: "#333333" },
	{ tag: tags.paren,             color: "#333333" },
	{ tag: tags.brace,             color: "#333333" },
	{ tag: tags.punctuation,       color: "#333333" },
	{ tag: tags.separator,         color: "#333333" },

	// ── Special ───────────────────────────────────────────────────────
	{ tag: tags.labelName,                  color: "#795E26" },
	{ tag: tags.special(tags.variableName), color: "#795E26" },
]);

function getLanguageExtension() {
	switch (props.language) {
		case "javascript":
		case "js":
			return javascript();
		case "python":
		default:
			return python();
	}
}

onMounted(() => {
	if (!editorEl.value) return;

	const languageCompartment = new Compartment();
	const extensions = [
		logixLightTheme,
		lineNumbers(),
		highlightActiveLine(),
		highlightActiveLineGutter(),
		history(),
		foldGutter(),
		indentOnInput(),
		bracketMatching(),
		syntaxHighlighting(logixHighlightStyle),
		syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
		languageCompartment.of(getLanguageExtension()),
		keymap.of([...defaultKeymap, ...historyKeymap, ...foldKeymap, indentWithTab]),
		readOnlyCompartment.of(EditorState.readOnly.of(props.readOnly)),
		EditorView.updateListener.of((update) => {
			if (update.docChanged && !ignoreNextUpdate) {
				const val = update.state.doc.toString();
				emit("update:modelValue", val);
				emit("change");
			}
			ignoreNextUpdate = false;
		}),
		EditorView.lineWrapping,
	];

	if (props.placeholder) {
		extensions.push(cmPlaceholder(props.placeholder));
	}

	const state = EditorState.create({
		doc: props.modelValue || "",
		extensions,
	});

	view = new EditorView({
		state,
		parent: editorEl.value,
	});
});

onBeforeUnmount(() => {
	if (view) {
		view.destroy();
		view = null;
	}
});

// ── Sync external changes into the editor ─────────────────────────────
watch(() => props.modelValue, (newVal) => {
	if (!view) return;
	const currentVal = view.state.doc.toString();
	if (newVal !== currentVal) {
		ignoreNextUpdate = true;
		view.dispatch({
			changes: {
				from: 0,
				to: currentVal.length,
				insert: newVal || "",
			},
		});
	}
});

// ── Sync readOnly changes ─────────────────────────────────────────────
watch(() => props.readOnly, (val) => {
	if (!view) return;
	view.dispatch({
		effects: readOnlyCompartment.reconfigure(EditorState.readOnly.of(val)),
	});
});

// ── Expose focus method ───────────────────────────────────────────────
function focus() {
	view?.focus();
}

defineExpose({ focus });
</script>

<style scoped>
.cm-editor-wrap {
	flex: 1;
	display: flex;
	overflow: hidden;
	height: 100%;
}

.cm-editor-wrap :deep(.cm-editor) {
	flex: 1;
	height: 100%;
}
</style>
