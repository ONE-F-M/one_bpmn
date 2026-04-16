import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import {
	Button,
	Input,
	setConfig,
	frappeRequest,
	resourcesPlugin,
	FormControl,
	Dialog,
	Badge,
	Tooltip,
	Avatar,
	ListView,
	Alert,
	initSocket,
} from "frappe-ui"

import "./main.css"

const app = createApp(App)

setConfig("resourceFetcher", frappeRequest)
app.use(resourcesPlugin)

// Initialize Socket.IO for realtime updates
const socket = initSocket()
app.config.globalProperties.$socket = socket

// Expose socket as window.frappe.realtime so components can use
// window.frappe.realtime.on/off for custom event listeners.
// Only polyfill when missing — don't overwrite if Frappe desk already provides it.
if (!window.frappe) window.frappe = { _is_bpmn_polyfill: true }
if (!window.frappe.realtime) {
	window.frappe.realtime = {
		on: (event, fn) => socket.on(event, fn),
		off: (event, fn) => socket.off(event, fn),
		emit: (event, ...args) => socket.emit(event, ...args),
	}
}

// Register global components
app.component("Button", Button)
app.component("Input", Input)
app.component("FormControl", FormControl)
app.component("Dialog", Dialog)
app.component("Badge", Badge)
app.component("Tooltip", Tooltip)
app.component("Avatar", Avatar)
app.component("ListView", ListView)
app.component("Alert", Alert)

app.use(router)

router.isReady().then(async () => {
	if (import.meta.env.DEV) {
		await frappeRequest({
			url: "/api/method/one_bpmn.www.spiff.get_context_for_dev",
		}).then(async (values) => {
			if (!window.frappe) window.frappe = {}
			window.frappe.boot = values
		}).catch(() => {
			// Ignore if method doesn't exist in dev mode
			console.log("Dev context not available, continuing...")
		})
	}
	app.mount("#app")
})
