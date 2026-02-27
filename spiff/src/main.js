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
} from "frappe-ui"

import "./main.css"

const app = createApp(App)

setConfig("resourceFetcher", frappeRequest)
app.use(resourcesPlugin)

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
