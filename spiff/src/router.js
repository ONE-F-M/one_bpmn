import { createRouter, createWebHistory } from "vue-router"
import Home from "@/pages/Processes.vue"
import Editor from "@/pages/Process.vue"
import VersionHistory from "@/pages/VersionHistory.vue"
import InstanceList from "@/pages/Instances.vue"
import InstanceDetail from "@/pages/Instance.vue"

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
		path: "/processa/process/:process/diagram/:diagram/history",
		name: "VersionHistory",
		component: VersionHistory,
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
		path: "/processa/runs",
		name: "Runs",
		component: () => import("@/pages/Runs.vue"),
	},
	{
		path: "/processa/runs/:run",
		name: "RunDetail",
		component: () => import("@/pages/Run.vue"),
	},
	{
		path: "/processa/insights",
		name: "Insights",
		component: () => import("@/pages/Insights.vue"),
	},
	{
		// What the checks found, ordered by time — the read-only counterpart to
		// the suites list, which is ordered by what you configure.
		path: "/processa/evals/results",
		name: "EvalResults",
		component: () => import("@/pages/EvalResults.vue"),
	},
	{
		path: "/processa/evals",
		name: "Evals",
		component: () => import("@/pages/Evals.vue"),
	},
	{
		path: "/processa/evals/feedback",
		name: "EvalFeedback",
		component: () => import("@/pages/EvalFeedback.vue"),
	},
	{
		path: "/processa/evals/suite/:suite",
		name: "EvalSuiteDetail",
		component: () => import("@/pages/EvalSuite.vue"),
		props: true,
	},
	{
		path: "/processa/evals/run/:run",
		name: "EvalRunReview",
		component: () => import("@/pages/EvalRun.vue"),
		props: true,
	},
	{
		// Run B is optional — a run created as half of an A/B pair
		// finds its own other side, so the pair is reachable from one id.
		path: "/processa/evals/compare/:runA/:runB?",
		name: "EvalComparison",
		component: () => import("@/pages/EvalComparison.vue"),
		props: true,
	},
	{
		path: "/processa/security",
		name: "Security",
		component: () => import("@/pages/Security.vue"),
	},
	{
		path: '/processa/skills',
		name: 'Skills',
		component: () => import('@/pages/Skills.vue'),
	},
	{
		path: "/processa/a2a",
		name: "A2A",
		component: () => import("@/pages/A2A.vue"),
	},
	{
		path: "/processa/sessions",
		name: "Sessions",
		component: () => import("@/pages/Sessions.vue"),
	},
	{
		path: "/processa/memory",
		name: "Memory",
		component: () => import("@/pages/Memory.vue"),
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
