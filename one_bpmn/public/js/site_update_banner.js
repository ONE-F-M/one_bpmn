// Site-update countdown banner for the Frappe desk (the Processa app has its own
// SiteUpdateBanner.vue). Server contract: one_bpmn/api/site_update.py.
(function () {
	// One place to adjust if the server method or event is renamed.
	const COUNTDOWN_METHOD = "one_bpmn.api.site_update.get_site_update_countdown";
	const COUNTDOWN_EVENT = "site_update_countdown";

	let timer = null;
	let banner = null;
	let endsAt = null; // epoch ms

	// The server sends UTC; a bare timestamp without an offset must not be read as local time.
	function parse_utc(iso) {
		if (!iso) return NaN;
		return Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : iso + "Z");
	}

	function clock(seconds) {
		const pad = (n) => String(n).padStart(2, "0");
		return pad(Math.floor(seconds / 60)) + ":" + pad(seconds % 60);
	}

	function stop() {
		clearInterval(timer);
		timer = null;
		endsAt = null;
		if (banner) banner.remove();
		banner = null;
	}

	function tick() {
		const left = Math.ceil((endsAt - Date.now()) / 1000);
		if (left <= 0) return stop();
		if (!banner) {
			banner = document.createElement("div");
			banner.setAttribute("role", "alert");
			banner.style.cssText =
				"position:fixed;top:0;left:0;right:0;z-index:2000;padding:8px 16px;text-align:center;" +
				"font-weight:600;color:var(--white, #fff);background:var(--red-600, #dc2626);";
			document.body.appendChild(banner);
		}
		banner.textContent = __(
			"This site will become unavailable in {0}. Any unsaved work will be lost.",
			[clock(left)]
		);
	}

	function start(payload) {
		if (!payload || payload.cancelled || payload.active === false) return stop();
		let end = parse_utc(payload.ends_at);
		if (Number.isNaN(end) && Number.isFinite(payload.seconds_remaining)) {
			end = Date.now() + payload.seconds_remaining * 1000;
		}
		if (Number.isNaN(end)) return stop();
		clearInterval(timer);
		endsAt = end;
		timer = setInterval(tick, 1000);
		tick();
	}

	$(document).on("startup", function () {
		frappe.realtime.on(COUNTDOWN_EVENT, start);
		frappe.call({ method: COUNTDOWN_METHOD, type: "GET" }).then((r) => start(r && r.message));
	});

	// The desk page lives until the tab closes; release the listener and timer then.
	window.addEventListener("beforeunload", function () {
		if (frappe.realtime && frappe.realtime.off) frappe.realtime.off(COUNTDOWN_EVENT, start);
		stop();
	});
})();
