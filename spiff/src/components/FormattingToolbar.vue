<template>
	<div class="formatting-toolbar flex items-center gap-2 min-w-0 overflow-hidden flex-nowrap">
		<!-- Fill Color Picker -->
		<div class="relative" ref="fillPickerRef">
			<button
				@click="toggleFillPicker"
				title="Fill Color"
				:disabled="!hasSelection"
				:class="[
					'p-1.5 rounded transition-colors flex items-center gap-0.5 h-8',
					hasSelection
						? 'hover:bg-gray-100 text-gray-700'
						: 'text-gray-300 cursor-not-allowed',
				]"
			>
				<div class="flex flex-col items-center gap-0.5">
					<Icon icon="lucide:paint-bucket" class="w-4 h-4" />
					<div
						class="w-4 h-1 rounded-sm border border-gray-300"
						:style="{ backgroundColor: selectedFillColor }"
					></div>
				</div>
				<Icon icon="lucide:chevron-down" class="w-3 h-3" />
			</button>
			<div
				v-if="showFillPicker"
				class="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-[1000]"
				style="min-width: 200px"
			>
				<div class="text-xs text-gray-500 mb-2 font-medium">Fill Color</div>
				<div class="grid grid-cols-6 gap-2">
					<button
						v-for="color in fillColors"
						:key="color.value"
						@click="applyFillColor(color.value)"
						:title="color.label"
						class="w-6 h-6 rounded-md border border-gray-200 hover:scale-110 transition-transform focus:outline-none focus:ring-2 focus:ring-blue-400"
						:style="{ backgroundColor: color.value }"
						:class="{
							'ring-2 ring-blue-500 ring-offset-1': selectedFillColor === color.value,
						}"
					></button>
				</div>
				<button
					@click="clearFillColor"
					class="mt-3 w-full text-xs text-gray-500 hover:text-gray-700 py-1.5 hover:bg-gray-50 rounded border border-gray-200"
				>
					Reset to Default
				</button>
			</div>
		</div>

		<!-- Stroke Color Picker -->
		<div class="relative" ref="strokePickerRef">
			<button
				@click="toggleStrokePicker"
				title="Line Color"
				:disabled="!hasSelection"
				:class="[
					'p-1.5 rounded transition-colors flex items-center gap-0.5 h-8',
					hasSelection
						? 'hover:bg-gray-100 text-gray-700'
						: 'text-gray-300 cursor-not-allowed',
				]"
			>
				<div class="flex flex-col items-center gap-0.5">
					<Icon icon="lucide:pencil-line" class="w-4 h-4" />
					<div
						class="w-4 h-1 rounded-sm border border-gray-300"
						:style="{ backgroundColor: selectedStrokeColor }"
					></div>
				</div>
				<Icon icon="lucide:chevron-down" class="w-3 h-3" />
			</button>
			<div
				v-if="showStrokePicker"
				class="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-[1000]"
				style="min-width: 200px"
			>
				<div class="text-xs text-gray-500 mb-2 font-medium">Line Color</div>
				<div class="grid grid-cols-6 gap-2">
					<button
						v-for="color in strokeColors"
						:key="color.value"
						@click="applyStrokeColor(color.value)"
						:title="color.label"
						class="w-6 h-6 rounded-md border border-gray-200 hover:scale-110 transition-transform focus:outline-none focus:ring-2 focus:ring-blue-400"
						:style="{ backgroundColor: color.value }"
						:class="{
							'ring-2 ring-blue-500 ring-offset-1':
								selectedStrokeColor === color.value,
						}"
					></button>
				</div>
				<button
					@click="clearStrokeColor"
					class="mt-3 w-full text-xs text-gray-500 hover:text-gray-700 py-1.5 hover:bg-gray-50 rounded border border-gray-200"
				>
					Reset to Default
				</button>
			</div>
		</div>

		<!-- Separator -->
		<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

		<!-- Bold Toggle -->
		<button
			@click="toggleBold"
			title="Bold"
			:disabled="!hasSelection"
			:class="[
				'min-w-[28px] h-8 flex items-center justify-center rounded transition-colors font-bold text-sm',
				!hasSelection
					? 'text-gray-300 cursor-not-allowed'
					: isBold
						? 'bg-blue-100 text-blue-700 shadow-[inset_0_1px_2px_rgba(0,0,0,0.1)]'
						: 'hover:bg-gray-100 text-gray-700',
			]"
		>
			B
		</button>

		<!-- Italic Toggle -->
		<button
			@click="toggleItalic"
			title="Italic"
			:disabled="!hasSelection"
			:class="[
				'min-w-[28px] h-8 flex items-center justify-center rounded transition-colors italic text-sm font-serif',
				!hasSelection
					? 'text-gray-300 cursor-not-allowed'
					: isItalic
						? 'bg-blue-100 text-blue-700 shadow-[inset_0_1px_2px_rgba(0,0,0,0.1)]'
						: 'hover:bg-gray-100 text-gray-700',
			]"
		>
			I
		</button>

		<!-- Underline Toggle -->
		<button
			@click="toggleUnderline"
			title="Underline"
			:disabled="!hasSelection"
			:class="[
				'min-w-[28px] h-8 flex items-center justify-center rounded transition-colors underline text-sm',
				!hasSelection
					? 'text-gray-300 cursor-not-allowed'
					: isUnderline
						? 'bg-blue-100 text-blue-700 shadow-[inset_0_1px_2px_rgba(0,0,0,0.1)]'
						: 'hover:bg-gray-100 text-gray-700',
			]"
		>
			U
		</button>

		<!-- Font Family Dropdown -->
		<div class="relative" ref="fontFamilyPickerRef">
			<button
				@click="toggleFontFamilyPicker"
				title="Font Family"
				:disabled="!hasSelection"
				:class="[
					'px-2 h-7 rounded transition-colors flex items-center gap-1 text-[13px] min-w-[80px] justify-between border',
					hasSelection
						? 'hover:bg-gray-50 text-gray-700 border-gray-200 bg-white'
						: 'text-gray-300 cursor-not-allowed border-gray-100 bg-white',
				]"
			>
				<span class="truncate">{{ selectedFontFamilyLabel }}</span>
				<Icon icon="lucide:chevron-down" class="w-3 h-3 flex-shrink-0" />
			</button>
			<div
				v-if="showFontFamilyPicker"
				class="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-[1000]"
				style="min-width: 150px"
			>
				<button
					v-for="font in fontFamilies"
					:key="font.value"
					@click="applyFontFamily(font.value)"
					class="w-full px-3 py-1.5 text-left text-sm hover:bg-gray-100 transition-colors"
					:style="{ fontFamily: font.value }"
					:class="{
						'bg-blue-50 text-blue-700': selectedFontFamily === font.value,
					}"
				>
					{{ font.label }}
				</button>
			</div>
		</div>

		<!-- Font Size Dropdown -->
		<div class="relative" ref="fontSizePickerRef">
			<button
				@click="toggleFontSizePicker"
				title="Font Size"
				:disabled="!hasSelection"
				:class="[
					'px-2 h-7 rounded transition-colors flex items-center gap-1 text-[13px] min-w-[50px] justify-between border',
					hasSelection
						? 'hover:bg-gray-50 text-gray-700 border-gray-200 bg-white'
						: 'text-gray-300 cursor-not-allowed border-gray-100 bg-white',
				]"
			>
				<span>{{ selectedFontSize }}</span>
				<Icon icon="lucide:chevron-down" class="w-3 h-3" />
			</button>
			<div
				v-if="showFontSizePicker"
				class="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-[1000]"
				style="min-width: 60px"
			>
				<button
					v-for="size in fontSizes"
					:key="size"
					@click="applyFontSize(size)"
					class="w-full px-3 py-1 text-left text-sm hover:bg-gray-100 transition-colors"
					:class="{
						'bg-blue-50 text-blue-700': selectedFontSize === size,
					}"
				>
					{{ size }}
				</button>
			</div>
		</div>

		<!-- Separator -->
		<div class="w-px h-5 bg-gray-200 mx-1 shrink-0"></div>

		<!-- Text Color Picker -->
		<div class="relative" ref="textColorPickerRef">
			<button
				@click="toggleTextColorPicker"
				title="Text Color"
				:disabled="!hasSelection"
				:class="[
					'p-1.5 rounded transition-colors flex items-center gap-0.5 h-8',
					hasSelection
						? 'hover:bg-gray-100 text-gray-700'
						: 'text-gray-300 cursor-not-allowed',
				]"
			>
				<div class="flex flex-col items-center gap-0.5">
					<Icon icon="lucide:type" class="w-4 h-4" />
					<div
						class="w-4 h-1 rounded-sm border border-gray-300"
						:style="{ backgroundColor: selectedTextColor }"
					></div>
				</div>
				<Icon icon="lucide:chevron-down" class="w-3 h-3" />
			</button>
			<div
				v-if="showTextColorPicker"
				class="absolute top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-[1000]"
				style="min-width: 200px"
			>
				<div class="text-xs text-gray-500 mb-2 font-medium">Text Color</div>
				<div class="grid grid-cols-6 gap-2">
					<button
						v-for="color in textColors"
						:key="color.value"
						@click="applyTextColor(color.value)"
						:title="color.label"
						class="w-6 h-6 rounded-md border border-gray-200 hover:scale-110 transition-transform focus:outline-none focus:ring-2 focus:ring-blue-400"
						:style="{ backgroundColor: color.value }"
						:class="{
							'ring-2 ring-blue-500 ring-offset-1': selectedTextColor === color.value,
						}"
					></button>
				</div>
				<button
					@click="clearTextColor"
					class="mt-3 w-full text-xs text-gray-500 hover:text-gray-700 py-1.5 hover:bg-gray-50 rounded border border-gray-200"
				>
					Reset to Default
				</button>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, toRaw } from "vue";
import { Icon } from "@iconify/vue";
import { getTextStyle, setTextStyle, DEFAULT_TEXT_STYLE } from "@/utils/textStyleUtils";

// Props
const props = defineProps({
	selectedElements: {
		type: Array,
		default: () => [],
	},
	modeler: {
		type: Object,
		default: null,
	},
});

// Emit events
const emit = defineEmits(["colorChanged"]);

// Refs for click outside
const fillPickerRef = ref(null);
const strokePickerRef = ref(null);
const textColorPickerRef = ref(null);
const fontFamilyPickerRef = ref(null);
const fontSizePickerRef = ref(null);

// Picker visibility state
const showFillPicker = ref(false);
const showStrokePicker = ref(false);
const showTextColorPicker = ref(false);
const showFontFamilyPicker = ref(false);
const showFontSizePicker = ref(false);

// Selected colors (for UI indicator)
const selectedFillColor = ref("#ffffff");
const selectedStrokeColor = ref("#1f2937");
const selectedTextColor = ref("#1f2937");

// Text style state
const isBold = ref(false);
const isItalic = ref(false);
const isUnderline = ref(false);
const selectedFontFamily = ref("Inter");
const selectedFontSize = ref(12);

// Font family options
const fontFamilies = [
	{ label: "Inter", value: "Inter" },
	{ label: "Arial", value: "Arial" },
	{ label: "Helvetica", value: "Helvetica" },
	{ label: "Times New Roman", value: "Times New Roman" },
	{ label: "Georgia", value: "Georgia" },
	{ label: "Verdana", value: "Verdana" },
	{ label: "Courier New", value: "Courier New" },
	{ label: "Trebuchet MS", value: "Trebuchet MS" },
];

// Font size options
const fontSizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48];

// Computed font family label for button
const selectedFontFamilyLabel = computed(() => {
	const font = fontFamilies.find(f => f.value === selectedFontFamily.value);
	return font ? font.label : "Inter";
});

// Extended color palettes with more options
const fillColors = [
	// Row 1: White to light grays
	{ label: "White", value: "#ffffff" },
	{ label: "Light Gray", value: "#f9fafb" },
	{ label: "Gray 100", value: "#f3f4f6" },
	{ label: "Gray 200", value: "#e5e7eb" },
	{ label: "Gray 300", value: "#d1d5db" },
	{ label: "Gray 400", value: "#9ca3af" },
	// Row 2: Blues
	{ label: "Blue 50", value: "#eff6ff" },
	{ label: "Blue 100", value: "#dbeafe" },
	{ label: "Blue 200", value: "#bfdbfe" },
	{ label: "Blue 300", value: "#93c5fd" },
	{ label: "Blue 400", value: "#60a5fa" },
	{ label: "Blue 500", value: "#3b82f6" },
	// Row 3: Greens
	{ label: "Green 50", value: "#f0fdf4" },
	{ label: "Green 100", value: "#dcfce7" },
	{ label: "Green 200", value: "#bbf7d0" },
	{ label: "Green 300", value: "#86efac" },
	{ label: "Green 400", value: "#4ade80" },
	{ label: "Green 500", value: "#22c55e" },
	// Row 4: Yellows/Oranges
	{ label: "Yellow 50", value: "#fefce8" },
	{ label: "Yellow 100", value: "#fef3c7" },
	{ label: "Yellow 200", value: "#fde68a" },
	{ label: "Orange 100", value: "#ffedd5" },
	{ label: "Orange 200", value: "#fed7aa" },
	{ label: "Orange 300", value: "#fdba74" },
	// Row 5: Reds/Pinks
	{ label: "Red 50", value: "#fef2f2" },
	{ label: "Red 100", value: "#fee2e2" },
	{ label: "Red 200", value: "#fecaca" },
	{ label: "Pink 100", value: "#fce7f3" },
	{ label: "Pink 200", value: "#fbcfe8" },
	{ label: "Pink 300", value: "#f9a8d4" },
	// Row 6: Purples/Cyans
	{ label: "Purple 50", value: "#faf5ff" },
	{ label: "Purple 100", value: "#f3e8ff" },
	{ label: "Purple 200", value: "#e9d5ff" },
	{ label: "Cyan 100", value: "#cffafe" },
	{ label: "Cyan 200", value: "#a5f3fc" },
	{ label: "Cyan 300", value: "#67e8f9" },
];

const strokeColors = [
	// Row 1: Blacks/Grays
	{ label: "Black", value: "#000000" },
	{ label: "Gray 900", value: "#111827" },
	{ label: "Gray 800", value: "#1f2937" },
	{ label: "Gray 700", value: "#374151" },
	{ label: "Gray 600", value: "#4b5563" },
	{ label: "Gray 500", value: "#6b7280" },
	// Row 2: Blues
	{ label: "Blue 900", value: "#1e3a8a" },
	{ label: "Blue 800", value: "#1e40af" },
	{ label: "Blue 700", value: "#1d4ed8" },
	{ label: "Blue 600", value: "#2563eb" },
	{ label: "Blue 500", value: "#3b82f6" },
	{ label: "Blue 400", value: "#60a5fa" },
	// Row 3: Greens
	{ label: "Green 900", value: "#14532d" },
	{ label: "Green 800", value: "#166534" },
	{ label: "Green 700", value: "#15803d" },
	{ label: "Green 600", value: "#16a34a" },
	{ label: "Green 500", value: "#22c55e" },
	{ label: "Green 400", value: "#4ade80" },
	// Row 4: Yellows/Oranges
	{ label: "Yellow 700", value: "#a16207" },
	{ label: "Yellow 600", value: "#ca8a04" },
	{ label: "Orange 700", value: "#c2410c" },
	{ label: "Orange 600", value: "#ea580c" },
	{ label: "Orange 500", value: "#f97316" },
	{ label: "Amber 500", value: "#f59e0b" },
	// Row 5: Reds/Pinks
	{ label: "Red 900", value: "#7f1d1d" },
	{ label: "Red 800", value: "#991b1b" },
	{ label: "Red 700", value: "#b91c1c" },
	{ label: "Red 600", value: "#dc2626" },
	{ label: "Pink 600", value: "#db2777" },
	{ label: "Pink 500", value: "#ec4899" },
	// Row 6: Purples/Cyans
	{ label: "Purple 800", value: "#6b21a8" },
	{ label: "Purple 700", value: "#7c3aed" },
	{ label: "Purple 600", value: "#9333ea" },
	{ label: "Cyan 700", value: "#0e7490" },
	{ label: "Cyan 600", value: "#0891b2" },
	{ label: "Cyan 500", value: "#06b6d4" },
];

// Text colors (reuse stroke colors for text)
const textColors = strokeColors;

// Computed
const hasSelection = computed(() => {
	return props.selectedElements && props.selectedElements.length > 0;
});

// Watch for selection changes to update color and text style indicators
watch(
	() => props.selectedElements,
	(newSelection) => {
		if (newSelection && newSelection.length > 0) {
			// Get colors from the first selected element
			const element = newSelection[0];
			const di = element.di;
			if (di) {
				// Read colors from BPMN DI (diagram interchange)
				const fill = di.get("bioc:fill") || di.get("color:background-color");
				const stroke = di.get("bioc:stroke") || di.get("color:border-color");
				if (fill) selectedFillColor.value = fill;
				if (stroke) selectedStrokeColor.value = stroke;
			}
			
			// Read text styles from element properties
			const textStyle = getTextStyle(element);
			isBold.value = textStyle.fontWeight === "bold";
			isItalic.value = textStyle.fontStyle === "italic";
			isUnderline.value = textStyle.textDecoration === "underline";
			selectedTextColor.value = textStyle.textColor;
			selectedFontFamily.value = textStyle.fontFamily || "Inter";
			selectedFontSize.value = textStyle.fontSize || 12;
		} else {
			// Reset state when nothing selected
			isBold.value = false;
			isItalic.value = false;
			isUnderline.value = false;
			selectedTextColor.value = DEFAULT_TEXT_STYLE.textColor;
			selectedFontFamily.value = "Inter";
			selectedFontSize.value = 12;
		}
	},
	{ immediate: true }
);

// Methods
function toggleFillPicker() {
	if (!hasSelection.value) return;
	showFillPicker.value = !showFillPicker.value;
	showStrokePicker.value = false;
	showTextColorPicker.value = false;
}

function toggleStrokePicker() {
	if (!hasSelection.value) return;
	showStrokePicker.value = !showStrokePicker.value;
	showFillPicker.value = false;
	showTextColorPicker.value = false;
}

function applyFillColor(color) {
	if (!props.modeler || !hasSelection.value) return;

	try {
		const modeling = props.modeler.get("modeling");
		// Use toRaw to unwrap Vue proxy - bpmn-js needs raw objects
		const rawElements = props.selectedElements.map(el => toRaw(el));
		modeling.setColor(rawElements, { fill: color });
		selectedFillColor.value = color;
		emit("colorChanged", { type: "fill", color });
	} catch (e) {
		console.error("Error applying fill color:", e);
	}

	showFillPicker.value = false;
}

function applyStrokeColor(color) {
	if (!props.modeler || !hasSelection.value) return;

	try {
		const modeling = props.modeler.get("modeling");
		// Use toRaw to unwrap Vue proxy - bpmn-js needs raw objects
		const rawElements = props.selectedElements.map(el => toRaw(el));
		modeling.setColor(rawElements, { stroke: color });
		selectedStrokeColor.value = color;
		emit("colorChanged", { type: "stroke", color });
	} catch (e) {
		console.error("Error applying stroke color:", e);
	}

	showStrokePicker.value = false;
}

function clearFillColor() {
	applyFillColor("#ffffff");
}

function clearStrokeColor() {
	applyStrokeColor("#1f2937");
}

// Text styling methods
function toggleBold() {
	if (!props.modeler || !hasSelection.value) return;
	
	try {
		const modeling = props.modeler.get("modeling");
		const newWeight = isBold.value ? "normal" : "bold";
		
		props.selectedElements.forEach((element) => {
			setTextStyle(modeling, toRaw(element), { fontWeight: newWeight });
		});
		
		isBold.value = !isBold.value;
		emit("colorChanged", { type: "textStyle", style: "bold", value: isBold.value });
	} catch (e) {
		console.error("Error toggling bold:", e);
	}
}

function toggleItalic() {
	if (!props.modeler || !hasSelection.value) return;
	
	try {
		const modeling = props.modeler.get("modeling");
		const newStyle = isItalic.value ? "normal" : "italic";
		
		props.selectedElements.forEach((element) => {
			setTextStyle(modeling, toRaw(element), { fontStyle: newStyle });
		});
		
		isItalic.value = !isItalic.value;
		emit("colorChanged", { type: "textStyle", style: "italic", value: isItalic.value });
	} catch (e) {
		console.error("Error toggling italic:", e);
	}
}

function toggleUnderline() {
	if (!props.modeler || !hasSelection.value) return;
	
	try {
		const modeling = props.modeler.get("modeling");
		const newDecoration = isUnderline.value ? "none" : "underline";
		
		props.selectedElements.forEach((element) => {
			setTextStyle(modeling, toRaw(element), { textDecoration: newDecoration });
		});
		
		isUnderline.value = !isUnderline.value;
		emit("colorChanged", { type: "textStyle", style: "underline", value: isUnderline.value });
	} catch (e) {
		console.error("Error toggling underline:", e);
	}
}

function toggleTextColorPicker() {
	if (!hasSelection.value) return;
	showTextColorPicker.value = !showTextColorPicker.value;
	showFillPicker.value = false;
	showStrokePicker.value = false;
}

function applyTextColor(color) {
	if (!props.modeler || !hasSelection.value) return;

	try {
		const modeling = props.modeler.get("modeling");
		
		props.selectedElements.forEach((element) => {
			setTextStyle(modeling, toRaw(element), { textColor: color });
		});
		
		selectedTextColor.value = color;
		emit("colorChanged", { type: "textColor", color });
	} catch (e) {
		console.error("Error applying text color:", e);
	}

	showTextColorPicker.value = false;
}

function clearTextColor() {
	applyTextColor(DEFAULT_TEXT_STYLE.textColor);
}

// Font family methods
function toggleFontFamilyPicker() {
	if (!hasSelection.value) return;
	showFontFamilyPicker.value = !showFontFamilyPicker.value;
	showFillPicker.value = false;
	showStrokePicker.value = false;
	showTextColorPicker.value = false;
	showFontSizePicker.value = false;
}

function applyFontFamily(fontFamily) {
	if (!props.modeler || !hasSelection.value) return;

	try {
		const modeling = props.modeler.get("modeling");
		
		props.selectedElements.forEach((element) => {
			setTextStyle(modeling, toRaw(element), { fontFamily });
		});
		
		selectedFontFamily.value = fontFamily;
		emit("colorChanged", { type: "fontFamily", value: fontFamily });
	} catch (e) {
		console.error("Error applying font family:", e);
	}

	showFontFamilyPicker.value = false;
}

// Font size methods
function toggleFontSizePicker() {
	if (!hasSelection.value) return;
	showFontSizePicker.value = !showFontSizePicker.value;
	showFillPicker.value = false;
	showStrokePicker.value = false;
	showTextColorPicker.value = false;
	showFontFamilyPicker.value = false;
}

function applyFontSize(fontSize) {
	if (!props.modeler || !hasSelection.value) return;

	try {
		const modeling = props.modeler.get("modeling");
		
		props.selectedElements.forEach((element) => {
			const rawElement = toRaw(element);
			
			// Get current font size before applying new one
			const currentStyle = getTextStyle(rawElement);
			const oldFontSize = currentStyle.fontSize || 12;
			
			// Apply the new font size
			setTextStyle(modeling, rawElement, { fontSize });
			
			// Auto-resize element to fit larger text (Bug #2 fix)
			// Only resize shapes that have bounds (not connections)
			if (rawElement.width && rawElement.height && rawElement.type !== "bpmn:SequenceFlow") {
				// Only resize if font is getting larger
				if (fontSize > oldFontSize) {
					// Calculate scale factor based on font size increase
					const scaleFactor = fontSize / oldFontSize;
					
					// Get element name for width estimation
					const name = rawElement.businessObject?.name || "";
					const textLength = name.length;
					
					// Estimate required dimensions
					// Font width is approximately 0.6 * fontSize per character
					const estimatedTextWidth = textLength * fontSize * 0.6;
					// Add padding (20px on each side)
					const requiredWidth = estimatedTextWidth + 40;
					// Height needs to accommodate text with padding
					const requiredHeight = fontSize * 2.5 + 40;
					
					// Take the max of current size scaled up or required size
					const scaledWidth = rawElement.width * scaleFactor;
					const scaledHeight = rawElement.height * scaleFactor;
					
					const newWidth = Math.max(rawElement.width, requiredWidth, scaledWidth);
					const newHeight = Math.max(rawElement.height, requiredHeight, scaledHeight);
					
					// Apply minimum sizes for BPMN elements
					const finalWidth = Math.max(100, Math.ceil(newWidth));
					const finalHeight = Math.max(80, Math.ceil(newHeight));
					
					// Resize if dimensions increased
					if (finalWidth > rawElement.width || finalHeight > rawElement.height) {
						modeling.resizeShape(rawElement, {
							x: rawElement.x,
							y: rawElement.y,
							width: finalWidth,
							height: finalHeight
						});
					}
				}
			}
		});
		
		selectedFontSize.value = fontSize;
		emit("colorChanged", { type: "fontSize", value: fontSize });
	} catch (e) {
		console.error("Error applying font size:", e);
	}

	showFontSizePicker.value = false;
}

// Click outside handler
function handleClickOutside(event) {
	if (fillPickerRef.value && !fillPickerRef.value.contains(event.target)) {
		showFillPicker.value = false;
	}
	if (strokePickerRef.value && !strokePickerRef.value.contains(event.target)) {
		showStrokePicker.value = false;
	}
	if (textColorPickerRef.value && !textColorPickerRef.value.contains(event.target)) {
		showTextColorPicker.value = false;
	}
	if (fontFamilyPickerRef.value && !fontFamilyPickerRef.value.contains(event.target)) {
		showFontFamilyPicker.value = false;
	}
	if (fontSizePickerRef.value && !fontSizePickerRef.value.contains(event.target)) {
		showFontSizePicker.value = false;
	}
}

onMounted(() => {
	document.addEventListener("click", handleClickOutside);
});

onUnmounted(() => {
	document.removeEventListener("click", handleClickOutside);
});
</script>
