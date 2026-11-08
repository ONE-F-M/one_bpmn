import { test, vi } from "vitest";
import assert from "node:assert/strict";
import { ref } from "vue";
import { useEditorDocu } from "../../src/composables/Editor/useEditorDocu.js";

function makeContext(panel = {}) {
	const steps = [];
	const ed = {
		props: { modelName: "Model A", process: "Process A" },
		docuPanel: ref({
			show: false,
			element: null,
			doctype: "",
			attr: "",
			_eventBus: null,
			...panel,
		}),
		modeler: null,
		onReady: (step) => steps.push(step),
	};
	useEditorDocu(ed);
	return { ed, steps };
}

const shape = (id, type, name, extra = {}) => ({
	id,
	businessObject: { id, name, $type: type, ...extra },
	incoming: [],
	outgoing: [],
});

test("the process context describes the step, its role and its neighbours", () => {
	const upstream = shape("Start", "bpmn:StartEvent", "Request received");
	const downstream = shape("Done", "bpmn:EndEvent", "Closed");
	const task = shape("Task_1", "bpmn:UserTask", "Review", {
		documentation: [{ text: "  Check the request  " }],
	});
	task.incoming = [{ source: upstream }];
	task.outgoing = [{ target: downstream }];
	const { ed } = makeContext({ element: task, attr: "targetDoctype" });
	const context = ed.docuProcessContext.value;
	assert.equal(context.element_type, "user task (a step a person completes)");
	assert.equal(context.field_role, "the record a person fills in or works on at this step");
	assert.equal(context.element_description, "Check the request");
	assert.deepEqual(context.upstream, ["Request received"]);
	assert.deepEqual(context.downstream, ["Closed"]);
	assert.equal(context.process_name, "Model A");
});

test("an unknown shape type is described in plain words", () => {
	const { ed } = makeContext({ element: shape("G1", "bpmn:ExclusiveGateway", "Choice") });
	assert.equal(ed.docuProcessContext.value.element_type, "exclusive gateway");
});

test("applying a DocType writes its name back through the launching event bus", () => {
	const fire = vi.fn();
	const { ed } = makeContext({ _eventBus: { fire } });
	ed.onDocuApplied("Vehicle Inspection");
	assert.deepEqual(fire.mock.calls[0], [
		"docu.doctype.update",
		{ doctype: "Vehicle Inspection" },
	]);
	ed.onDocuApplied("");
	assert.equal(fire.mock.calls.length, 1);
});

test("the launch event opens the panel with the doctype, field and event bus", () => {
	const { ed, steps } = makeContext();
	const handlers = {};
	const bus = { on: (name, fn) => (handlers[name] = fn) };
	ed.modeler = { get: () => bus };
	steps.forEach((step) => step());
	const element = shape("Task_2", "bpmn:UserTask", "Fill");
	const launcher = { fire: vi.fn() };
	handlers["launch-docu-editor"]({
		element,
		doctype: "Claim",
		attr: "targetDoctype",
		eventBus: launcher,
	});
	assert.equal(ed.docuPanel.value.show, true);
	assert.equal(ed.docuPanel.value.doctype, "Claim");
	assert.equal(ed.docuPanel.value.attr, "targetDoctype");
	assert.equal(ed.docuPanel.value._eventBus.fire, launcher.fire);
});
