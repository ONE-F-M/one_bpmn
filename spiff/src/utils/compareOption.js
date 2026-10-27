// Autocomplete's default compareFn reads .value on a null model and throws, which blocks picking an option
export function compareOption(a, b) {
	return a?.value === b?.value;
}
