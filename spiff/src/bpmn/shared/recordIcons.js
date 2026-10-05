import { h } from "preact";

export const CHEVRON = "M7 10l5 5 5-5z";
export const CLOSE = "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z";
export const CHECK = "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z";
export const PLUS = "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z";

export function icon(path) {
	return h("svg", { viewBox: "0 0 24 24", width: 18, height: 18, "aria-hidden": "true" }, h("path", { d: path }));
}

// A Workflow State's style as a colour dot; an unknown style is grey.
export function dot(style) {
	return h("span", { class: `wfs-dot wfs-dot--${(style || "none").toLowerCase()}`, "aria-hidden": "true" });
}
