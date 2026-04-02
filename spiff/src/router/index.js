import { createRouter, createWebHistory } from "vue-router"
import Home from "@/views/Home.vue"
import Editor from "@/views/Editor.vue"
import InstanceList from "@/views/InstanceList.vue"
import InstanceDetail from "@/views/InstanceDetail.vue"

const routes = [
	{
		path: "/processa",
		name: "Home",
		component: Home,
	},
	{
		path: "/processa/process/:process",
		name: "ProcessEditor",
		component: Editor,
		props: true,
	},
	{
		path: "/processa/process/:process/diagram/:diagram",
		name: "DiagramEditor",
		component: Editor,
		props: true,
	},
	{
		path: "/processa/instances",
		name: "InstanceList",
		component: InstanceList,
	},
	{
		path: "/processa/instances/:instance",
		name: "InstanceDetail",
		component: InstanceDetail,
	},
	{
		path: "/:pathMatch(.*)*",
		redirect: "/processa",
	},
]

const router = createRouter({
	history: createWebHistory(),
	routes,
})

export default router
