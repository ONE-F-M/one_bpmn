import { createRouter, createWebHistory } from "vue-router"
import Home from "@/views/Home.vue"
import Editor from "@/views/Editor.vue"

const routes = [
	{
		path: "/spiff",
		name: "Home",
		component: Home,
	},
	{
		path: "/spiff/process/:process",
		name: "ProcessEditor",
		component: Editor,
		props: true,
	},
	{
		path: "/spiff/process/:process/diagram/:diagram",
		name: "DiagramEditor",
		component: Editor,
		props: true,
	},
	{
		path: "/:pathMatch(.*)*",
		redirect: "/spiff",
	},
]

const router = createRouter({
	history: createWebHistory(),
	routes,
})

export default router
