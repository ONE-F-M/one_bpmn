import {
	SelectEntry,
	isSelectEntryEdited,
} from "@bpmn-io/properties-panel";
import { useService } from "bpmn-js-properties-panel";
import { getBusinessObject } from "bpmn-js/lib/util/ModelUtil";
import { h } from "preact";

let _doctypeCache = null;
let _doctypeFetching = false;

let _userCache = null;
let _userFetching = false;

const _docfieldCache = new Map();
const _docfieldFetching = new Set();

function loadDoctypes(onLoaded) {
	if (_doctypeCache) { onLoaded(_doctypeCache); return; }
	if (_doctypeFetching) return;
	_doctypeFetching = true;
	fetch(
		'/api/resource/DocType?fields=["name"]&limit_page_length=9999&order_by=name+asc',
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			_doctypeCache = [
				{ label: "-- Select DocType --", value: "" },
				...data.map((d) => ({ label: d.name, value: d.name })),
			];
			_doctypeFetching = false;
			onLoaded(_doctypeCache);
		})
		.catch((e) => {
			console.error("[UserTask] fetch DocTypes:", e);
			_doctypeCache = [{ label: "-- Error loading --", value: "" }];
			_doctypeFetching = false;
			onLoaded(_doctypeCache);
		});
}

function loadUsers(onLoaded) {
	if (_userCache) { onLoaded(_userCache); return; }
	if (_userFetching) return;
	_userFetching = true;
	const filters = encodeURIComponent(
		JSON.stringify([
			["user_type", "=", "System User"],
			["enabled", "=", 1],
		])
	);
	fetch(
		`/api/resource/User?fields=["name","full_name"]&filters=${filters}&limit_page_length=9999&order_by=full_name+asc`,
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			_userCache = [
				{ label: "-- Select User --", value: "" },
				...data.map((d) => ({ label: `${d.full_name} (${d.name})`, value: d.name })),
			];
			_userFetching = false;
			onLoaded(_userCache);
		})
		.catch((e) => {
			console.error("[UserTask] fetch Users:", e);
			_userCache = [{ label: "-- Error loading --", value: "" }];
			_userFetching = false;
			onLoaded(_userCache);
		});
}

function loadDocfields(doctype, onLoaded) {
	if (!doctype) return;
	if (_docfieldCache.has(doctype)) { onLoaded(_docfieldCache.get(doctype)); return; }
	if (_docfieldFetching.has(doctype)) return;
	_docfieldFetching.add(doctype);
	const filters = encodeURIComponent(
		JSON.stringify([
			["parent", "=", doctype],
			["fieldtype", "=", "Link"],
			["options", "=", "User"],
		])
	);
	fetch(
		`/api/resource/DocField?fields=["fieldname","label"]&filters=${filters}&limit_page_length=500`,
		{ credentials: "include" }
	)
		.then((r) => r.json())
		.then((json) => {
			const data = json.data || json.message || [];
			const options = [
				{ label: "-- Select Docfield --", value: "" },
				...data.map((d) => ({ label: `${d.label} (${d.fieldname})`, value: d.fieldname })),
			];
			_docfieldCache.set(doctype, options);
			_docfieldFetching.delete(doctype);
			onLoaded(options);
		})
		.catch((e) => {
			console.error("[UserTask] fetch Docfields:", e);
			const err = [{ label: "-- Error loading --", value: "" }];
			_docfieldCache.set(doctype, err);
			_docfieldFetching.delete(doctype);
			onLoaded(err);
		});
}

// Helpers
function getAttr(bo, attr) {
	return bo.get(`spiffworkflow:${attr}`) || "";
}

function touchElement(modeling, element, bo) {
	const mode = bo.get("spiffworkflow:assigneeMode");
	modeling.updateModdleProperties(element, bo, {
		"spiffworkflow:assigneeMode": mode,
	});
}

export function UserTaskProps(props) {
	const { element } = props;
	const bo = getBusinessObject(element);
	const assigneeMode = getAttr(bo, "assigneeMode");

	const entries = [
		{
			id: "spiffworkflow-assigneeMode",
			element,
			component: AssigneeModeComponent,
			isEdited: isSelectEntryEdited,
		},
	];

	if (assigneeMode === "User") {
		entries.push({
			id: "spiffworkflow-assigneeUser",
			element,
			component: AssigneeUserComponent,
			isEdited: isSelectEntryEdited,
		});
	} else if (assigneeMode === "Docfield") {
		entries.push({
			id: "spiffworkflow-targetDoctype",
			element,
			component: TargetDoctypeComponent,
			isEdited: isSelectEntryEdited,
		});
		entries.push({
			id: "spiffworkflow-assigneeDocfield",
			element,
			component: AssigneeDocfieldComponent,
			isEdited: isSelectEntryEdited,
		});
	}

	return entries;
}

// Component 1 - Assignee Mode
function AssigneeModeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const getValue = () => getAttr(bo, "assigneeMode");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeMode": value || undefined,
			"spiffworkflow:targetDoctype": undefined,
			"spiffworkflow:assigneeUser": undefined,
			"spiffworkflow:assigneeDocfield": undefined,
		});
	};

	const getOptions = () => [
		{ label: translate("-- Select Assignee Mode --"), value: "" },
		{ label: translate("User"), value: "User" },
		{ label: translate("Docfield"), value: "Docfield" },
	];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignee Mode"),
		getValue,
		setValue,
		getOptions,
	});
}

// Component 2 - Assignee User
function AssigneeUserComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	if (!_userCache && !_userFetching) {
		loadUsers(() => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "assigneeUser");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeUser": value || undefined,
		});
	};

	const getOptions = () =>
		_userCache || [{ label: translate("Loading..."), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignee User"),
		getValue,
		setValue,
		getOptions,
	});
}

// Component 3 - Target Doctype
function TargetDoctypeComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	if (!_doctypeCache && !_doctypeFetching) {
		loadDoctypes(() => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "targetDoctype");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:targetDoctype": value || undefined,
			"spiffworkflow:assigneeDocfield": undefined,
		});
		if (value) {
			loadDocfields(value, () => touchElement(modeling, element, bo));
		}
	};

	const getOptions = () =>
		_doctypeCache || [{ label: translate("Loading..."), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Target DocType"),
		getValue,
		setValue,
		getOptions,
	});
}

// Component 4 - Assignee Docfield
function AssigneeDocfieldComponent(props) {
	const { element, id } = props;
	const modeling = useService("modeling");
	const translate = useService("translate");
	const bo = getBusinessObject(element);

	const doctype = getAttr(bo, "targetDoctype");

	if (doctype && !_docfieldCache.has(doctype) && !_docfieldFetching.has(doctype)) {
		loadDocfields(doctype, () => touchElement(modeling, element, bo));
	}

	const getValue = () => getAttr(bo, "assigneeDocfield");

	const setValue = (value) => {
		modeling.updateModdleProperties(element, bo, {
			"spiffworkflow:assigneeDocfield": value || undefined,
		});
	};

	const getOptions = () =>
		_docfieldCache.get(doctype) ||
		[{ label: doctype ? translate("Loading...") : translate("-- Select Target DocType first --"), value: "" }];

	return h(SelectEntry, {
		element,
		id,
		label: translate("Assignee Docfield"),
		getValue,
		setValue,
		getOptions,
	});
}
