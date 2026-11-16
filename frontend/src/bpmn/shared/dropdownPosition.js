/**
 * Viewport-anchored placement for .bpmn-dropdown-list.
 *
 * The list is position:fixed so it can escape the properties panel's
 * overflow clipping (the panel scrolls, so absolute children are cut off
 * at the group border). Callers pass the anchor input element; the list
 * opens below it, or flips above when the viewport bottom is too close.
 *
 * Components using this must re-render on document scroll (capture) and
 * window resize so the list follows its anchor.
 */
export function fixedDropdownStyle(anchorEl, maxHeight = 200) {
	if (!anchorEl) return {};
	const rect = anchorEl.getBoundingClientRect();
	const spaceBelow = window.innerHeight - rect.bottom;
	const style = {
		left: `${rect.left}px`,
		width: `${rect.width}px`,
	};
	if (spaceBelow < maxHeight + 12 && rect.top > spaceBelow) {
		style.bottom = `${window.innerHeight - rect.top + 4}px`;
	} else {
		style.top = `${rect.bottom + 4}px`;
	}
	return style;
}
