import { h, Component, render } from "preact";
import { createApp, defineComponent, h as vueH, shallowReactive } from "vue";
import RecordPicker from "@/components/Controls/RecordPicker/RecordPicker.vue";
import { frappeGet } from "./frappeResource";
import { joinValues, splitValues, toOptions } from "@/utils/recordPicker";
import "./bpmn-panel.css";

const PREACT_HOST = defineComponent({
	props: { build: { type: Function, required: true } },
	mounted() {
		render(this.build(), this.$el);
	},
	updated() {
		render(this.build(), this.$el);
	},
	unmounted() {
		render(null, this.$el);
	},
	render() {
		return vueH("div");
	},
});

async function fetchDocTypes(txt) {
	const params = { fields: '["name"]', limit_page_length: 50, order_by: "name asc" };
	if (txt) params.filters = JSON.stringify([["name", "like", `%${txt}%`]]);
	const rows = await frappeGet("/api/resource/DocType", params);
	return Array.isArray(rows) ? rows : [];
}

/**
 * Properties-panel entry that mounts the Vue RecordPicker.
 * Props: id, label, value, onChange(value, option), fetchApi(txt) or loadOptions(), valueField,
 * renderOption, multiple, translate, placeholder, createRecord, renderCreate, missingText.
 * Single mode stores the picked name; multiple mode stores a comma-separated string.
 */
export class RecordPickerField extends Component {
	// One stable function, so the picker does not reload on every panel re-render.
	fetchOptions = async (txt) => {
		const { loadOptions, fetchApi, valueField, renderOption } = this.props;
		return toOptions(
			await (loadOptions || fetchApi || fetchDocTypes)(txt),
			valueField,
			renderOption,
		);
	};

	componentDidMount() {
		this.vueProps = shallowReactive(this.pickerProps());
		this.app = createApp({ render: () => vueH(RecordPicker, this.vueProps, this.slots()) });
		this.app.mount(this.mountEl);
	}

	componentDidUpdate() {
		Object.assign(this.vueProps, this.pickerProps());
	}

	componentWillUnmount() {
		this.app?.unmount();
	}

	slots() {
		const { renderCreate } = this.props;
		if (!renderCreate) return undefined;
		return {
			create: ({ query, done, cancel }) =>
				vueH(PREACT_HOST, {
					build: () =>
						renderCreate({ initialName: query, onCreated: done, onCancel: cancel }),
				}),
		};
	}

	pickerProps() {
		const {
			id,
			value,
			multiple,
			translate,
			placeholder,
			loadOptions,
			onChange,
			createRecord,
			missingText,
			keepTyped,
		} = this.props;
		return {
			id,
			multiple: Boolean(multiple),
			modelValue: multiple ? splitValues(value) : value || "",
			placeholder: placeholder || (multiple ? "Type to search..." : ""),
			translate: translate || ((text) => text),
			localSearch: Boolean(loadOptions),
			fetchOptions: this.fetchOptions,
			createRecord,
			allowFreeText: multiple ? "" : loadOptions ? (keepTyped ? "blur" : "") : "live",
			missingText: missingText || "",
			"onUpdate:modelValue": (next) => onChange(multiple ? joinValues(next) : next),
		};
	}

	render({ id, label, multiple, itemLabel = "item", value }) {
		const count = multiple ? splitValues(value).length : 0;
		return h("div", { class: "bio-properties-panel-entry", "data-entry-id": id }, [
			label && h("label", { for: id, class: "bio-properties-panel-label" }, label),
			h("div", { ref: (el) => (this.mountEl = el) }),
			count > 0 &&
				h(
					"div",
					{ class: "bio-properties-panel-description" },
					`${count} ${itemLabel}${count !== 1 ? "s" : ""} selected`,
				),
		]);
	}
}
