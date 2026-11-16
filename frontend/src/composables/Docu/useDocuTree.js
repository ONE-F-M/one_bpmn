import { computed, reactive, ref } from "vue";
import { FIELD_FLAGS, STRUCTURAL } from "@/utils/docuFieldDefs";

export function useDocuTree() {
	// Top-level builder view - mirrors Frappe's Form / Settings tabs.
	const view = ref("form"); // 'form' | 'settings'
	// Which section's "…" options menu is open (Frappe's section Dropdown).
	const openMenu = ref(null);

	// Builder tree (tabs → sections → columns → fields)
	// The tree is the working model while editing; the flat IR fields[] the
	// backend expects is derived on demand in currentIr(). Each node wraps a
	// `df` (the real field dict - spread-preserved so agent-generated attrs
	// survive the round-trip) and keeps its own drag id off the df.
	const tabs = ref([]);
	const activeTabIndex = ref(0);
	const activeTab = computed(() => tabs.value[activeTabIndex.value] || null);

	// selection: { type: 'form'|'field'|'section'|'column'|'tab', node }
	const sel = reactive({ type: "form", node: null });

	let uid = 0;
	const nid = () => `n${++uid}`;

	// Tree node factories
	function normalizeDf(f) {
		// Preserve every incoming attribute (spread) so props the builder does not
		// render - fetch_from, precision, mandatory_depends_on, … - survive the
		// round-trip; then coerce the UI-bound flags to booleans for the checkboxes.
		const df = { ...f };
		df.label = f.label || "";
		df.fieldname = f.fieldname || "";
		df.fieldtype = f.fieldtype || "Data";
		df.options = f.options || "";
		df.default = f.default || "";
		df.description = f.description || "";
		df.depends_on = f.depends_on || "";
		for (const flag of FIELD_FLAGS) df[flag] = !!f[flag];
		return reactive(df);
	}
	function makeBreak(fieldtype) {
		return reactive({ fieldtype, label: "", fieldname: "", description: "" });
	}
	function wrapTab(df) {
		return reactive({ id: nid(), df: df || null, sections: [] });
	}
	function wrapSection(df) {
		return reactive({ id: nid(), df: df || null, columns: [] });
	}
	function wrapColumn(df) {
		return reactive({ id: nid(), df: df || null, fields: [] });
	}
	function wrapField(df) {
		return reactive({ id: nid(), df });
	}

	// flat fields[] → tree (lazy: implicit containers created only when needed, so a
	// leading break never leaves an empty container in front of it)
	function buildTree(raw) {
		const t = [];
		let ct = null,
			cs = null,
			cc = null;
		const pushTab = (df) => {
			ct = wrapTab(df);
			t.push(ct);
			cs = null;
			cc = null;
		};
		const pushSection = (df) => {
			if (!ct) pushTab(null);
			cs = wrapSection(df);
			ct.sections.push(cs);
			cc = null;
		};
		const pushColumn = (df) => {
			if (!cs) pushSection(null);
			cc = wrapColumn(df);
			cs.columns.push(cc);
		};
		const pushField = (df) => {
			if (!cc) pushColumn(null);
			cc.fields.push(wrapField(df));
		};

		for (const f of raw || []) {
			const df = normalizeDf(f);
			switch (df.fieldtype) {
				case "Tab Break":
					pushTab(df);
					break;
				case "Section Break":
					pushSection(df);
					break;
				case "Column Break":
					pushColumn(df);
					break;
				default:
					pushField(df);
			}
		}
		tabs.value = t;
		ensureStructure();
		activeTabIndex.value = 0;
	}

	// Guarantee there is always at least one tab / section / column to drop into.
	function ensureStructure() {
		if (!tabs.value.length) tabs.value.push(wrapTab(null));
		for (const tab of tabs.value) {
			if (!tab.sections.length) tab.sections.push(wrapSection(null));
			for (const s of tab.sections) {
				if (!s.columns.length) s.columns.push(wrapColumn(null));
			}
		}
		if (activeTabIndex.value >= tabs.value.length) activeTabIndex.value = 0;
	}

	// tree → flat fields[] (implicit containers with df=null emit nothing)
	function flatten() {
		const out = [];
		for (const tab of tabs.value) {
			if (tab.df) out.push(tab.df);
			for (const s of tab.sections) {
				if (s.df) out.push(s.df);
				for (const c of s.columns) {
					if (c.df) out.push(c.df);
					for (const f of c.fields) out.push(f.df);
				}
			}
		}
		return out;
	}

	const contentCount = computed(
		() => flatten().filter((df) => !STRUCTURAL.has(df.fieldtype)).length,
	);

	// Selection
	function selectForm() {
		sel.type = "form";
		sel.node = null;
	}
	function selectField(w) {
		sel.type = "field";
		sel.node = w;
	}
	function selectContainer(kind, node) {
		if (!node.df) {
			node.df = makeBreak(
				{ section: "Section Break", column: "Column Break", tab: "Tab Break" }[kind],
			);
		}
		sel.type = kind;
		sel.node = node;
	}
	function isSel(kind, node) {
		return sel.type === kind && sel.node === node;
	}
	function isSelField(w) {
		return sel.type === "field" && sel.node === w;
	}

	function tabLabel(tab, i) {
		return (tab.df && tab.df.label) || (i === 0 ? "Details" : `Tab ${i + 1}`);
	}

	function autoName(df) {
		if (!df.fieldname && df.label && !STRUCTURAL.has(df.fieldtype)) {
			df.fieldname = df.label
				.trim()
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, "_")
				.replace(/^_+|_+$/g, "");
		}
	}

	// Add / remove
	function findColumnOfField(w) {
		for (const s of activeTab.value.sections)
			for (const c of s.columns) if (c.fields.includes(w)) return c;
		return null;
	}
	function findSectionOfColumn(col) {
		for (const s of activeTab.value.sections) if (s.columns.includes(col)) return s;
		return null;
	}

	function addFieldToColumn(col) {
		const w = wrapField(normalizeDf({ fieldtype: "Data", label: "", fieldname: "" }));
		col.fields.push(w);
		selectField(w);
	}
	function addTab() {
		const t = wrapTab(makeBreak("Tab Break"));
		const s = wrapSection(null);
		s.columns.push(wrapColumn(null));
		t.sections.push(s);
		tabs.value.push(t);
		activeTabIndex.value = tabs.value.length - 1;
		selectContainer("tab", t);
	}
	function removeTab(tab) {
		if (tabs.value.length <= 1) return; // always keep at least one tab
		const i = tabs.value.indexOf(tab);
		if (i < 0) return;
		tabs.value.splice(i, 1);
		if (activeTabIndex.value >= tabs.value.length)
			activeTabIndex.value = tabs.value.length - 1;
		ensureStructure();
		selectForm();
	}

	// Section "…" options menu (mirrors Frappe's Section Dropdown)
	function toggleMenu(section) {
		openMenu.value = openMenu.value === section ? null : section;
	}
	function sectionIndex(section) {
		return activeTab.value.sections.indexOf(section);
	}

	function addSectionBelow(section) {
		const s = wrapSection(makeBreak("Section Break"));
		s.columns.push(wrapColumn(null));
		const i = sectionIndex(section);
		activeTab.value.sections.splice(i + 1, 0, s);
		openMenu.value = null;
		selectContainer("section", s);
	}
	function removeSection(section) {
		const secs = activeTab.value.sections;
		const i = secs.indexOf(section);
		if (i >= 0) secs.splice(i, 1);
		openMenu.value = null;
		ensureStructure();
		selectForm();
	}
	function addColumnTo(section) {
		const c = wrapColumn(makeBreak("Column Break"));
		section.columns.push(c);
		openMenu.value = null;
		selectContainer("column", c);
	}
	function removeColumn(section) {
		// Remove the last column, moving its fields into the previous one (Frappe's behaviour).
		const cols = section.columns;
		if (cols.length <= 1) return;
		const last = cols[cols.length - 1];
		const prev = cols[cols.length - 2];
		prev.fields.push(...last.fields);
		cols.splice(cols.length - 1, 1);
		openMenu.value = null;
		selectForm();
	}
	function emptyColumn(section) {
		// Clear every field from the (single) column but keep the column.
		const col = section.columns[0];
		if (col) col.fields.splice(0);
		openMenu.value = null;
		selectForm();
	}
	function moveSectionsToTab(section) {
		// Move this section and every one after it into a fresh tab.
		const secs = activeTab.value.sections;
		const i = secs.indexOf(section);
		if (i < 0) return;
		const moved = secs.splice(i);
		const t = wrapTab(makeBreak("Tab Break"));
		t.sections = moved;
		tabs.value.push(t);
		openMenu.value = null;
		ensureStructure();
		activeTabIndex.value = tabs.value.length - 1;
		selectForm();
	}
	function sectionMenu(section) {
		const groups = [
			{
				group: "Section",
				items: [
					{ label: "Add section below", onClick: () => addSectionBelow(section) },
					{ label: "Remove section", onClick: () => removeSection(section) },
				],
			},
			{
				group: "Column",
				items: [{ label: "Add column", onClick: () => addColumnTo(section) }],
			},
		];
		if (section.columns.length > 1) {
			groups[1].items.push({ label: "Remove column", onClick: () => removeColumn(section) });
		} else if (section.columns[0] && section.columns[0].fields.length) {
			groups[1].items.push({ label: "Empty column", onClick: () => emptyColumn(section) });
		}
		if (sectionIndex(section) > 0) {
			groups[0].items.push({
				label: "Move to new tab",
				onClick: () => moveSectionsToTab(section),
			});
		}
		return groups;
	}

	function removeField(column, w) {
		const i = column.fields.indexOf(w);
		if (i >= 0) column.fields.splice(i, 1);
		if (sel.node === w) selectForm();
	}
	function duplicateField(column, w) {
		const src = w.df || {};
		const copy = normalizeDf({
			...src,
			fieldname: "",
			label: src.label || "" ? src.label + " Copy" : "",
		});
		const nw = wrapField(copy);
		const i = column.fields.indexOf(w);
		column.fields.splice(i + 1, 0, nw);
		selectField(nw);
	}
	// Add a new field directly after this one (Frappe's per-field "+" action).
	function addFieldAfter(column, w) {
		const nw = wrapField(normalizeDf({ fieldtype: "Data", label: "", fieldname: "" }));
		const i = column.fields.indexOf(w);
		column.fields.splice(i + 1, 0, nw);
		selectField(nw);
	}
	// Move this field and every field after it into a fresh column (Frappe's "move").
	function moveFieldsToNewColumn(column, w) {
		const section = findSectionOfColumn(column);
		if (!section) return;
		const i = column.fields.indexOf(w);
		if (i <= 0) return; // nothing to split off when it's already the first field
		const moved = column.fields.splice(i);
		const nc = wrapColumn(makeBreak("Column Break"));
		nc.fields = moved;
		const ci = section.columns.indexOf(column);
		section.columns.splice(ci + 1, 0, nc);
		selectField(w);
	}
	function deleteSelected() {
		if (sel.type === "field" && sel.node) {
			const col = findColumnOfField(sel.node);
			if (col) removeField(col, sel.node);
			return;
		}
		if (sel.type === "section" && sel.node) {
			const secs = activeTab.value.sections;
			const i = secs.indexOf(sel.node);
			if (i >= 0) secs.splice(i, 1);
		} else if (sel.type === "column" && sel.node) {
			const s = findSectionOfColumn(sel.node);
			if (s) {
				const i = s.columns.indexOf(sel.node);
				if (i >= 0) s.columns.splice(i, 1);
			}
		} else if (sel.type === "tab" && sel.node) {
			const i = tabs.value.indexOf(sel.node);
			if (i >= 0) tabs.value.splice(i, 1);
			if (activeTabIndex.value >= tabs.value.length)
				activeTabIndex.value = Math.max(0, tabs.value.length - 1);
		}
		ensureStructure();
		selectForm();
	}

	return {
		view,
		openMenu,
		tabs,
		activeTabIndex,
		activeTab,
		sel,
		buildTree,
		ensureStructure,
		flatten,
		contentCount,
		selectForm,
		selectField,
		selectContainer,
		isSel,
		isSelField,
		tabLabel,
		autoName,
		addFieldToColumn,
		addTab,
		removeTab,
		toggleMenu,
		sectionMenu,
		removeField,
		duplicateField,
		addFieldAfter,
		moveFieldsToNewColumn,
		deleteSelected,
	};
}
