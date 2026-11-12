import { computed } from "vue";

export function useAgentConfigModels(ac) {
	const { catalogModels, siteDefaults, form } = ac;

	// The catalog narrowed to the chosen provider. Left whole when no provider is
	// chosen, so a model with no provider linked still surfaces with its warning
	// rather than quietly disappearing.
	const filteredCatalogModels = computed(() => {
		if (!form.value.aiProvider) return catalogModels.value;
		return catalogModels.value.filter((m) => m.provider === form.value.aiProvider);
	});

	// Picking a provider narrows the models to that provider's, so a model left
	// over from another one no longer belongs and is cleared — saving the pair as
	// it stood would write a provider and a model that disagree.
	function onProviderChange() {
		if (!form.value.aiProvider || !form.value.aiModel) return;
		const current = catalogModels.value.find((m) => m.name === form.value.aiModel);
		if (current && current.provider !== form.value.aiProvider) form.value.aiModel = "";
	}

	// A model without Support Temperature is sent neither value; a model missing from the catalogue keeps both editable.
	const samplingSupported = computed(() => {
		const picked = catalogModels.value.find((m) => m.name === form.value.aiModel);
		return !picked || Boolean(picked.support_temperature);
	});

	// The pair has to agree from both directions: a model belongs to exactly one
	// provider, so picking one settles the provider too.
	function onModelChange() {
		const picked = catalogModels.value.find((m) => m.name === form.value.aiModel);
		if (picked?.provider) form.value.aiProvider = picked.provider;
	}
	// A <select> whose bound value matches no option renders blank, which reads as
	// "nothing is set" for a field that IS set — and invites someone to correct it
	// by picking something else. So whenever the chosen model is not among the
	// options listed, the field carries one for it, saying why: absent from the
	// catalogue, or belonging to a different provider than the one chosen. The
	// second only reaches a person on a shape saved before the two had to agree.
	function unlistedModelLabel(model) {
		if (!model || filteredCatalogModels.value.some((m) => m.name === model)) return "";
		const known = catalogModels.value.find((m) => m.name === model);
		if (!known) return `${model} (not in catalog)`;
		// Its own name, not modelLabel(): a model with no provider linked is exactly
		// the one a chosen provider always excludes, and stacking both clauses reads
		// as two separate faults instead of one.
		return `${known.model_name || known.name} — not a ${form.value.aiProvider} model`;
	}
	// What an option reads as: the model's name when it has one, else the
	// raw API id, and nothing else when it is usable. The provider is derived
	// from the model and repeating it on every row said nothing a designer
	// picking a model needed. A model that will NOT work is still listed —
	// hiding it is what produced an empty picker — and still says why.
	function modelLabel(m) {
		const label = m.model_name || m.name;
		if (!m.provider) return `${label} — no provider linked`;
		return m.has_credentials === false ? `${label} — no API key` : label;
	}

	function inheritLabel(which) {
		const name = siteDefaults.value[which];
		return name ? `-- Use the site default (${name}) --` : "-- Use the default --";
	}

	Object.assign(ac, {
		filteredCatalogModels,
		onProviderChange,
		samplingSupported,
		onModelChange,
		unlistedModelLabel,
		modelLabel,
		inheritLabel,
	});
}
