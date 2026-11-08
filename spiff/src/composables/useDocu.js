import { inject } from "vue";

export const DOCU_KEY = Symbol("docu-state");

export function useDocu() {
	return inject(DOCU_KEY);
}
