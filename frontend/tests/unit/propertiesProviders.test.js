import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/bpmn/signalPropertiesProvider/signalRecords", () => ({
	SIGNALS: { get: vi.fn(() => null), load: vi.fn(() => Promise.resolve()) },
}));
vi.mock("@/bpmn/signalPropertiesProvider/SignalListGroup", () => ({
	signalListGroup: vi.fn((args) => ({ id: "signals", args })),
}));
vi.mock("@/utils/serverMessage", () => ({ serverMessage: (error) => error.message }));
vi.mock("@/bpmn/signalPropertiesProvider/SignalField", () => ({
	signalSelect: vi.fn((translate) => Object.assign(() => null, { translate })),
}));

const { makeProvider } = await import("@/bpmn/shared/makePropertiesProvider");
const { default: timerModule } =
	await import("@/bpmn/timerPropertiesProvider/TimerPropertiesProvider");
const { default: signalModule } =
	await import("@/bpmn/signalPropertiesProvider/SignalPropertiesProvider");
const { SIGNALS } = await import("@/bpmn/signalPropertiesProvider/signalRecords");
const { signalListGroup } = await import("@/bpmn/signalPropertiesProvider/SignalListGroup");

const element = (types, extra = {}) => ({
	businessObject: { $instanceOf: (t) => types.includes(t), ...extra },
});
const definition = (type) => ({ $type: type, $instanceOf: (t) => t === type });
const translate = (text) => text;

function register(Provider, ...services) {
	const registered = [];
	const panel = {
		registerProvider: (priority, provider) => registered.push({ priority, provider }),
	};
	const provider = new Provider(panel, translate, ...services);
	return { registered, provider };
}

describe("makeProvider", () => {
	it("registers at the default priority and adds one group to the matching type", () => {
		const Provider = makeProvider("bpmn:Task", "group-a", "Group A", () => ["entry"]);
		const { registered, provider } = register(Provider);
		expect(registered[0].priority).toBe(500);
		expect(Provider.$inject).toEqual(["propertiesPanel", "translate"]);
		const groups = [{ id: "general" }];
		provider.getGroups(element(["bpmn:Task"]))(groups);
		expect(groups.map((g) => g.id)).toEqual(["general", "group-a"]);
		const other = [{ id: "general" }];
		provider.getGroups(element(["bpmn:Event"]))(other);
		expect(other).toEqual([{ id: "general" }]);
	});

	it("accepts several types", () => {
		const Provider = makeProvider(["bpmn:Task", "bpmn:Event"], "group-a", "Group A", () => []);
		const { provider } = register(Provider);
		for (const type of ["bpmn:Task", "bpmn:Event"]) {
			const groups = [];
			provider.getGroups(element([type]))(groups);
			expect(groups).toHaveLength(1);
		}
	});

	it("registers at the given priority and injects named services after the panel and translate", () => {
		const eventBus = { fire: vi.fn() };
		const setup = vi.fn(() => ({ ready: true }));
		const Provider = makeProvider("bpmn:Task", null, null, null, {
			priority: 400,
			inject: ["eventBus"],
			setup,
			edit: vi.fn(),
		});
		const { registered, provider } = register(Provider, eventBus);
		expect(registered[0].priority).toBe(400);
		expect(Provider.$inject).toEqual(["propertiesPanel", "translate", "eventBus"]);
		expect(setup).toHaveBeenCalledWith({ translate, eventBus });
		expect(provider.state).toEqual({ ready: true });
	});

	it("edits the existing groups instead of adding one when edit is given", () => {
		const edit = vi.fn(({ groups }) => groups[0].entries.push("added"));
		const Provider = makeProvider("bpmn:Task", null, null, null, { edit });
		const { provider } = register(Provider);
		const groups = [{ id: "general", entries: [] }];
		const target = element(["bpmn:Task"]);
		const result = provider.getGroups(target)(groups);
		expect(result).toBe(groups);
		expect(groups).toEqual([{ id: "general", entries: ["added"] }]);
		expect(edit).toHaveBeenCalledWith({ groups, element: target, state: undefined });
	});
});

describe("Timer provider", () => {
	const Provider = timerModule.timerPropertiesProvider[1];
	const timerEvent = element(["bpmn:Event"], {
		eventDefinitions: [definition("bpmn:TimerEventDefinition")],
	});

	it("is registered under the same name and priority as before", () => {
		const { registered } = register(Provider);
		expect(timerModule.__init__).toEqual(["timerPropertiesProvider"]);
		expect(timerModule.timerPropertiesProvider[0]).toBe("type");
		expect(registered[0].priority).toBe(500);
	});

	it("adds the description entry to the timer group of a timer event", () => {
		const { provider } = register(Provider);
		const timerGroup = { id: "timer", entries: [{ id: "timerEventDefinitionType" }] };
		provider.getGroups(timerEvent)([{ id: "general", entries: [] }, timerGroup]);
		expect(timerGroup.entries.map((e) => e.id)).toEqual([
			"timerEventDefinitionType",
			"timer-type-description",
		]);
		expect(timerGroup.entries[1].element).toBe(timerEvent);
		expect(typeof timerGroup.entries[1].component).toBe("function");
	});

	it("leaves other elements and groups alone", () => {
		const { provider } = register(Provider);
		const timerGroup = () => ({ id: "timer", entries: [] });
		const cases = [
			element(["bpmn:Event"], {
				eventDefinitions: [definition("bpmn:MessageEventDefinition")],
			}),
			element(["bpmn:Event"], {}),
			element(["bpmn:Task"], {
				eventDefinitions: [definition("bpmn:TimerEventDefinition")],
			}),
		];
		for (const target of cases) {
			const group = timerGroup();
			provider.getGroups(target)([group]);
			expect(group.entries).toEqual([]);
		}
		const groups = [{ id: "general", entries: [] }];
		expect(() => provider.getGroups(timerEvent)(groups)).not.toThrow();
		expect(groups).toEqual([{ id: "general", entries: [] }]);
	});
});

describe("Signal provider", () => {
	const Provider = signalModule.bpmnSignalMasterPropertiesProvider[1];
	const signalEvent = element(["bpmn:Event"], {
		eventDefinitions: [definition("bpmn:SignalEventDefinition")],
	});
	const processElement = element(["bpmn:Process"]);
	let eventBus;

	beforeEach(() => {
		eventBus = { fire: vi.fn() };
		SIGNALS.get.mockReset().mockReturnValue(null);
		SIGNALS.load.mockReset().mockResolvedValue(undefined);
		signalListGroup.mockClear();
	});

	it("is registered under the same name, at priority 400, with the event bus injected", () => {
		const { registered } = register(Provider, eventBus);
		expect(signalModule.__init__).toEqual(["bpmnSignalMasterPropertiesProvider"]);
		expect(signalModule.bpmnSignalMasterPropertiesProvider[0]).toBe("type");
		expect(registered[0].priority).toBe(400);
		expect(Provider.$inject).toEqual(["propertiesPanel", "translate", "eventBus"]);
	});

	it("swaps the select component of a signal event's signal group", () => {
		const { provider } = register(Provider, eventBus);
		const select = { id: "signal-select", component: "library" };
		provider.getGroups(signalEvent)([
			{ id: "signal-group", entries: [select, { id: "other" }] },
		]);
		expect(typeof select.component).toBe("function");
		expect(select.component.translate).toBe(translate);
	});

	it("replaces the signal list on a process and loads the signals once", async () => {
		const { provider } = register(Provider, eventBus);
		const groups = [{ id: "general" }, { id: "signals" }];
		provider.getGroups(processElement)(groups);
		expect(groups[1].id).toBe("signals");
		expect(groups[1].args.element).toBe(processElement);
		expect(groups[1].args.loadError).toBe("");
		expect(SIGNALS.load).toHaveBeenCalledTimes(1);
		await Promise.resolve();
		await Promise.resolve();
		expect(eventBus.fire).toHaveBeenCalledWith("elements.changed", {
			elements: [processElement],
		});
		groups[1].args.refresh();
		expect(eventBus.fire).toHaveBeenCalledTimes(2);
	});

	it("does not load again when the signals are already there", () => {
		SIGNALS.get.mockReturnValue([{ name: "A" }]);
		const { provider } = register(Provider, eventBus);
		provider.getGroups(processElement)([{ id: "signals" }]);
		expect(SIGNALS.load).not.toHaveBeenCalled();
	});

	it("keeps a load error, shows it on the next render and does not retry", async () => {
		SIGNALS.load.mockRejectedValue(new Error("No permission"));
		const { provider } = register(Provider, eventBus);
		provider.getGroups(processElement)([{ id: "signals" }]);
		await new Promise((resolve) => setTimeout(resolve, 0));
		const groups = [{ id: "signals" }];
		provider.getGroups(processElement)(groups);
		expect(groups[0].args.loadError).toContain("No permission");
		expect(SIGNALS.load).toHaveBeenCalledTimes(1);
	});

	it("keeps the drafts of one provider instance between renders", () => {
		const { provider } = register(Provider, eventBus);
		provider.getGroups(processElement)([{ id: "signals" }]);
		provider.getGroups(processElement)([{ id: "signals" }]);
		const [first, second] = signalListGroup.mock.calls.map(([args]) => args.drafts);
		expect(first).toBe(second);
	});

	it("leaves a process without a signals group and other elements alone", () => {
		const { provider } = register(Provider, eventBus);
		const groups = [{ id: "general" }];
		provider.getGroups(processElement)(groups);
		expect(groups).toEqual([{ id: "general" }]);
		expect(SIGNALS.load).not.toHaveBeenCalled();
		const timer = element(["bpmn:Event"], {
			eventDefinitions: [definition("bpmn:TimerEventDefinition")],
		});
		const select = { id: "signal-select", component: "library" };
		provider.getGroups(timer)([{ id: "signal-group", entries: [select] }]);
		expect(select.component).toBe("library");
	});
});
