import { computed } from "vue";
import { frappeRequest } from "frappe-ui";

export function useAgentConfigScreening(ac) {
	const { screeningControls, form, showNotice, serverMessage } = ac;

	// A control is hidden when the control it depends on is off. The server sends a
	// plain fieldname rather than the doctype's "eval:" expression, so nothing here
	// has to evaluate anything — and a dependency we could not reduce arrives as
	// null and the control simply renders, which is the safe direction.
	function isOn(fieldname) {
		const dep = screeningControls.value.find((c) => c.fieldname === fieldname);
		if (!dep) return true;
		return !(dep.value === 0 || dep.value === "0" || dep.value === false || dep.value == null);
	}
	// Kept as a plain list of names, which is what the server sends and expects
	// back. Sorted so the saved order does not churn on every tick.
	function toggleAllowed(control, choice, on) {
		const current = new Set(control.value || []);
		if (on) current.add(choice);
		else current.delete(choice);
		control.value = [...current].sort();
	}

	function visibleIn(group) {
		return group.controls.filter((c) => !c.depends_on_field || isOn(c.depends_on_field));
	}

	// Rendered group by group, in the order the server sent them. Grouping comes
	// from the server rather than a list here, for the same reason the controls
	// themselves do: a second copy in the Vue is one more thing to fall out of step.
	const controlGroups = computed(() => {
		const out = [];
		for (const c of screeningControls.value) {
			const name = c.group || "Screening";
			let g = out.find((x) => x.name === name);
			if (!g) out.push((g = { name, controls: [] }));
			g.controls.push(c);
		}
		return out;
	});

	async function loadScreening() {
		screeningControls.value = [];
		const name = form.value.aiAgentConfig;
		if (!name || name === "__create__") return;
		try {
			const r = await frappeRequest({
				url: "/api/method/one_bpmn.api.security.agent_screening",
				method: "POST",
				params: { agent: name },
			});
			screeningControls.value = (r && r.controls) || [];
		} catch {
			/* an unreadable agent simply shows no screening section */
		}
	}

	async function saveScreening() {
		const name = form.value.aiAgentConfig;
		if (!name || !screeningControls.value.length) return;
		const values = {};
		screeningControls.value.forEach((c) => {
			values[c.fieldname] = c.value;
		});
		try {
			await frappeRequest({
				url: "/api/method/one_bpmn.api.security.save_agent_screening",
				method: "POST",
				params: { agent: name, values: JSON.stringify(values) },
			});
		} catch (e) {
			showNotice("Screening settings not saved", serverMessage(e));
		}
	}

	Object.assign(ac, {
		isOn,
		toggleAllowed,
		visibleIn,
		controlGroups,
		loadScreening,
		saveScreening,
	});
}
