/**
 * Wrap an outside-click directive so it starts listening once the current click is done.
 * A v-if menu mounts while the click that opened it is still bubbling, and would otherwise catch it.
 */
export function afterOpeningClick(directive) {
	return {
		mounted: (el, binding, vnode) =>
			setTimeout(() => el.isConnected && directive.beforeMount(el, binding, vnode)),
		unmounted: directive.unmounted,
	};
}
