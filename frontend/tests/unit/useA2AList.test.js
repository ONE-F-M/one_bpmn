import { beforeEach, describe, expect, it, vi } from "vitest";

const frappeRequest = vi.fn();
vi.mock("frappe-ui", () => ({ frappeRequest: (...args) => frappeRequest(...args) }));

const { useA2AList } = await import("../../src/composables/useA2AList");

function makeList(filters = {}) {
	const onError = vi.fn();
	const list = useA2AList({
		url: "/api/method/x.list_things",
		rowsKey: "things",
		buildParams: () => filters,
		onError,
	});
	return { list, onError };
}

const page = (things, total, start) => ({ things, total, start });

beforeEach(() => frappeRequest.mockReset());

describe("useA2AList", () => {
	it("sends the filters first, then the page window", async () => {
		frappeRequest.mockResolvedValue(page([{ name: "a" }], 1, 0));
		const { list } = makeList({ direction: "Internal", state: undefined });
		await list.load(0);
		const { url, params } = frappeRequest.mock.calls[0][0];
		expect(url).toBe("/api/method/x.list_things");
		expect(JSON.stringify(params)).toBe('{"direction":"Internal","start":0,"page_length":20}');
		expect(list.rows.value).toEqual([{ name: "a" }]);
		expect(list.total.value).toBe(1);
	});

	it("sends the page size as a number when the select returns a string", async () => {
		frappeRequest.mockResolvedValue(page([], 120, 0));
		const { list } = makeList();
		list.pageLength.value = "50";
		await list.load(0);
		await list.next();
		expect(frappeRequest.mock.calls[0][0].params.page_length).toBe(50);
		expect(frappeRequest.mock.calls[1][0].params.start).toBe(50);
	});

	it("goes back one page at a time and never below the first", async () => {
		frappeRequest.mockResolvedValue(page([], 100, 10));
		const { list } = makeList();
		list.pageLength.value = 10;
		await list.load(10);
		await list.prev();
		await list.prev();
		const starts = frappeRequest.mock.calls.map((c) => c[0].params.start);
		expect(starts[1]).toBe(0);
		expect(starts[2]).toBe(0);
	});

	it("returns to the first page when the page size changes", async () => {
		frappeRequest.mockResolvedValue(page([], 100, 40));
		const { list } = makeList();
		await list.load(40);
		list.pageLength.value = 100;
		await list.changeSize();
		expect(frappeRequest.mock.calls[1][0].params).toMatchObject({
			start: 0,
			page_length: 100,
		});
	});

	it("falls back to 20 for a page size that is not a number", () => {
		const { list } = makeList();
		list.pageLength.value = "";
		expect(list.pageLengthNum.value).toBe(20);
	});

	it("reports the error, keeps the old rows, and stops loading", async () => {
		frappeRequest.mockResolvedValueOnce(page([{ name: "a" }], 1, 0));
		const { list, onError } = makeList();
		await list.load(0);
		frappeRequest.mockRejectedValueOnce(new Error("boom"));
		await list.load(0);
		expect(onError).toHaveBeenCalledWith("boom");
		expect(list.rows.value).toEqual([{ name: "a" }]);
		expect(list.loading.value).toBe(false);
	});
});
