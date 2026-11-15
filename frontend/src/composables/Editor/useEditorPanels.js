import { computed, nextTick, watch } from "vue";
import { useWindowSize } from "@/composables/useWindowSize";
import { useBottomSheet } from "@/composables/useBottomSheet";
import {
	isLockedElement as isPanelLockedElement,
	panelElement,
} from "@/bpmn/shared/releasedPanel";

export function useEditorPanels(ed) {
	const {
		props,
		showPropertiesPanel,
		propertiesCollapsed,
		selectedElements,
		showProsAllyPanel,
		prosAllyMounted,
		dragHandleRef,
	} = ed;

	// Is the panel in front of us actually editable? Released mode is per element:
	// a script task or an AI Agent task keeps its read-only panel even while the
	// rest of the map's properties are open for editing.
	const panelReleased = computed(() => {
		if (!props.readonly || !props.reassignMode) return false;
		const element = panelElement(selectedElements.value);
		return !!element && !isPanelLockedElement(element.businessObject);
	});

	// Mobile responsiveness
	const { isMobile } = useWindowSize();

	watch(showProsAllyPanel, (show) => {
		if (show) prosAllyMounted.value = true;
	});

	const { dragOffset, isDragging, attach: attachBottomSheet } = useBottomSheet();

	// This component is a single long-lived instance that survives switching
	// diagrams and entering version preview, so reset the panel when the editor
	// flips to read-only - otherwise it would stay open with its toggle gone.
	watch(
		() => props.readonly,
		(isReadonly) => {
			if (isReadonly) showProsAllyPanel.value = false;
		},
	);

	// Attach swipe-to-dismiss when the properties panel opens on mobile
	watch([showPropertiesPanel, isMobile], () => {
		if (showPropertiesPanel.value && isMobile.value) {
			nextTick(() => {
				if (dragHandleRef.value) {
					attachBottomSheet(dragHandleRef.value, () => {
						showPropertiesPanel.value = false;
					});
				}
			});
		}
	});

	function togglePropertiesCollapse() {
		propertiesCollapsed.value = !propertiesCollapsed.value;
	}

	Object.assign(ed, {
		panelReleased,
		togglePropertiesCollapse,
		isMobile,
		dragOffset,
		isDragging,
	});
}
