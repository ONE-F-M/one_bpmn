// Shared "AI sparkle" icon used for AI Agent Tasks — in the Change-element
// menu entry and in the canvas renderer, so both stay visually consistent.

export const AI_SPARKLE_SVG =
	'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#6366f1">' +
	'<path d="M12 2.5l1.9 6.1 6.1 1.9-6.1 1.9L12 18.5l-1.9-6.1L4 10.5l6.1-1.9z"/>' +
	'<path d="M18.7 13.5l.85 2.75L22.3 17.1l-2.75.85L18.7 20.7l-.85-2.75L15.1 17.1l2.75-.85z"/>' +
	"</svg>";

export const AI_SPARKLE_DATA_URI =
	"data:image/svg+xml;charset=utf-8," + encodeURIComponent(AI_SPARKLE_SVG);
