import clipboardModule from "@/utils/clipboard";
import nativeCopyPasteModule from "@/utils/nativeCopyPaste";

export { clipboardModule, nativeCopyPasteModule };

export function useEditorCopyPaste(ed) {
	ed.onReady(() => {
		const eventBus = ed.modeler.get("eventBus");
		// nativeCopyPasteModule fires 'native-copy-paste:error' on any
		// clipboard API failure (unavailable, permission denied, or parse
		// error). Log it here so it surfaces in the browser console.
		eventBus.on("native-copy-paste:error", ({ message, error }) => {
			console.warn("[native-copy-paste]", message, error);
		});
	});
}
