// Connector service-task panel — renders fields dynamically from the connector
// configuration served by the backend (BPMN Connector / Operation / Field
// DocTypes, projected by connectors/api.get_connector_manifests).
//
// The panel builds its entry list synchronously, so manifests come from the
// shared module-level cache in ../shared/connectorManifests (also used by the
// canvas icon renderer); when the fetch resolves it fires elements.changed to
// re-render the panel with the real fields. Nothing about a connector is
// hardcoded here — this file renders whatever the configuration declares.

import {
	SelectEntry,
	isSelectEntryEdited,
	TextFieldEntry,
	isTextFieldEntryEdited,
	TextAreaEntry,
	isTextAreaEntryEdited,
	CheckboxEntry,
	isCheckboxEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";
import {
	ensureChoices,
	ensureManifestsForElement,
	findManifest,
	getChoices,
	getManifests,
} from "../shared/connectorManifests";

function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) ?? "";
}
function getBoolAttr(bo, attr) {
	const raw = bo.get(`spiffworkflow:${attr}`);
	return raw === true || raw === "true";
}
function setAttr(modeling, element, bo, attr, value) {
	modeling.updateModdleProperties(element, bo, { [`spiffworkflow:${attr}`]: value || undefined });
}

function getParams(bo) {
	try {
		const p = JSON.parse(getAttr(bo, "connectorParams") || "{}");
		return p && typeof p === "object" ? p : {};
	} catch (e) {
		return {};
	}
}
function setParam(modeling, element, bo, key, val) {
	const p = getParams(bo);
	if (val === "" || val === undefined || val === null) delete p[key];
	else p[key] = val;
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:connectorParams": Object.keys(p).length ? JSON.stringify(p) : undefined,
	});
}

function fieldVisible(field, bo, operation) {
	const c = field.condition;
	if (!c) return true;
	const actual = c.field === "operation" ? operation : getParams(bo)[c.field];
	if (c.equals !== undefined) return actual === c.equals;
	if (Array.isArray(c.oneOf)) return c.oneOf.includes(actual);
	return true;
}

// ── Entry list ──────────────────────────────────────────────────────────────
export function connectorEntries(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const entries = [
		{ id: "spiffworkflow-connectorId", element, component: ConnectorIdComponent, isEdited: isSelectEntryEdited },
	];

	const connectorId = getAttr(bo, "connectorId");
	const manifest = findManifest(connectorId);
	if (!connectorId || !manifest) return entries; // still loading, or nothing chosen

	entries.push({ id: "spiffworkflow-operation", element, component: OperationComponent, isEdited: isSelectEntryEdited });

	const operation = getAttr(bo, "operation");
	const opSpec = (manifest.operations || []).find((o) => o.value === operation);
	if (!operation || !opSpec) return entries;

	(opSpec.fields || []).forEach((field) => {
		if (!fieldVisible(field, bo, operation)) return;
		entries.push(makeFieldEntry(element, field));
	});
	entries.push({ id: "spiffworkflow-resultVariable", element, component: ResultVariableComponent, isEdited: isTextFieldEntryEdited });
	entries.push({ id: "spiffworkflow-failOnError", element, component: FailOnErrorComponent, isEdited: isCheckboxEntryEdited });
	return entries;
}

// ── Components ────────────────────────────────────────────────────────────────
function ConnectorIdComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const eventBus = useService("eventBus");
	const bo = getBusinessObject(element);
	ensureManifestsForElement(eventBus, element);

	return h(SelectEntry, {
		element,
		id,
		label: translate("Connector"),
		getValue: () => getAttr(bo, "connectorId"),
		setValue: (value) =>
			modeling.updateModdleProperties(element, bo, {
				"spiffworkflow:connectorId": value || undefined,
				"spiffworkflow:operation": undefined,
				"spiffworkflow:connectorParams": undefined,
			}),
		getOptions: () => {
			const manifests = getManifests();
			const opts = [{ label: translate(manifests === null ? "Loading…" : "-- Select Connector --"), value: "" }];
			(manifests || []).forEach((m) => opts.push({ label: m.label || m.connectorId, value: m.connectorId }));
			return opts;
		},
	});
}

function OperationComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);
	const manifest = findManifest(getAttr(bo, "connectorId"));

	return h(SelectEntry, {
		element,
		id,
		label: translate("Operation"),
		getValue: () => getAttr(bo, "operation"),
		setValue: (value) =>
			modeling.updateModdleProperties(element, bo, {
				"spiffworkflow:operation": value || undefined,
				"spiffworkflow:connectorParams": undefined,
			}),
		getOptions: () => {
			const opts = [{ label: translate("-- Select Operation --"), value: "" }];
			((manifest && manifest.operations) || []).forEach((o) => opts.push({ label: o.label || o.value, value: o.value }));
			return opts;
		},
	});
}

function makeFieldEntry(element, field) {
	let isEdited = isTextFieldEntryEdited;
	if (field.type === "Dropdown") isEdited = isSelectEntryEdited;
	else if (field.type === "Boolean") isEdited = isCheckboxEntryEdited;
	else if (field.type === "Text") isEdited = isTextAreaEntryEdited;
	return {
		id: `connector-field-${field.name}`,
		element,
		component: (props) => FieldComponent({ ...props, field }),
		isEdited,
	};
}

function FieldComponent(props) {
	const { element, id, field } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const debounce = useService("debounceInput");
	const eventBus = useService("eventBus");
	const bo = getBusinessObject(element);
	const label = translate(field.label || field.name) + (field.required ? " *" : "");
	const read = () => {
		const v = getParams(bo)[field.name];
		return v === undefined ? field.default ?? "" : v;
	};

	// Dynamic dropdown: options come from the field's configured Choices From
	// path, resolved server-side. Sibling field values travel as context, so a
	// dependent dropdown re-fetches when the field it depends on changes.
	if (field.dynamicChoices) {
		const key = ensureChoices(
			getAttr(bo, "connectorId"),
			getAttr(bo, "operation"),
			field.name,
			getParams(bo),
			eventBus,
			element,
		);
		const loaded = getChoices(key);
		return h(SelectEntry, {
			element,
			id,
			label,
			getValue: read,
			setValue: (v) => setParam(modeling, element, bo, field.name, v),
			getOptions: () => [
				{ label: translate(loaded ? "-- Select --" : "Loading…"), value: "" },
				...(loaded || []).map((c) => ({ label: c.label, value: c.value })),
			],
		});
	}

	if (field.type === "Dropdown") {
		const choices = (field.choices || []).map((c) => (typeof c === "string" ? { label: c, value: c } : { label: c.label, value: c.value }));
		return h(SelectEntry, {
			element,
			id,
			label,
			getValue: read,
			setValue: (v) => setParam(modeling, element, bo, field.name, v),
			getOptions: () => [...(field.required ? [] : [{ label: translate("-- Select --"), value: "" }]), ...choices],
		});
	}
	if (field.type === "Boolean") {
		return h(CheckboxEntry, {
			element,
			id,
			label,
			getValue: () => {
				const v = getParams(bo)[field.name];
				return v === true || v === "true";
			},
			setValue: (v) => setParam(modeling, element, bo, field.name, v ? "true" : ""),
		});
	}
	const Entry = field.type === "Text" ? TextAreaEntry : TextFieldEntry;
	return h(Entry, {
		element,
		id,
		label,
		debounce,
		getValue: read,
		setValue: (v) => setParam(modeling, element, bo, field.name, v),
		description: field.help ? translate(field.help) : undefined,
	});
}

function ResultVariableComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const debounce = useService("debounceInput");
	const bo = getBusinessObject(element);
	return h(TextFieldEntry, {
		element,
		id,
		label: translate("Output variable"),
		debounce,
		getValue: () => getAttr(bo, "resultVariable"),
		setValue: (v) => setAttr(modeling, element, bo, "resultVariable", v),
		description: translate("Stores the result under this task-data key; downstream refs use {{ task_data.<var> }}."),
	});
}

function FailOnErrorComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);
	return h(CheckboxEntry, {
		element,
		id,
		label: translate("Fail workflow on error"),
		getValue: () => getBoolAttr(bo, "failOnError"),
		setValue: (v) => setAttr(modeling, element, bo, "failOnError", v ? "true" : ""),
	});
}
