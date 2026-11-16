import { computed } from "vue";
import { frappeRequest } from "frappe-ui";

export function useProductionReview(pc) {
	const {
		activeDiagramName,
		connectToProduction,
		instanceType,
		showReviewDialog,
		reviewKind,
		prBaseBranch,
		reviewStage,
		reviewChanges,
		reviewResult,
	} = pc;

	const isBaInstance = computed(() => instanceType.value === "BA");

	const isProductionInstance = computed(() => instanceType.value === "Production");

	const syncingLabel = computed(() =>
		reviewKind.value === "doctypes"
			? `Opening pull request against ${prBaseBranch.value}…`
			: "Syncing to Production…",
	);

	const reviewTitle = computed(() =>
		reviewKind.value === "doctypes" ? "Review Doctypes" : "Review Workflow Objects",
	);

	const reviewIntro = computed(() =>
		reviewKind.value === "doctypes"
			? "Doctypes referenced in the process model, alongside Client Scripts, Custom Fields and Property Setters, will be compared to the Production system for changes."
			: "Workflow Objects (Roles, Server Scripts, Workflow States, and Workflow Action Master) referenced in the process model will be compared to the Production system for changes.",
	);

	const reviewEmptyMessage = computed(() =>
		reviewKind.value === "doctypes"
			? "No changes seen in the relevant doctype(s)"
			: "No changes seen in the relevant workflow objects.",
	);

	async function loadProductionReviewSettings() {
		try {
			const r = await frappeRequest({
				url: "/api/method/processa.api.production_review.production_review_settings",
			});
			const d = r.message || r;
			connectToProduction.value = !!d.connect_to_production;
			instanceType.value = d.instance_type || "";
			prBaseBranch.value = d.pr_base_branch || "";
		} catch {
			connectToProduction.value = false;
			instanceType.value = "";
		}
	}

	function openReview(kind) {
		reviewKind.value = kind;
		reviewStage.value = "intro";
		reviewChanges.value = [];
		reviewResult.value = null;
		showReviewDialog.value = true;
	}

	function closeReview() {
		showReviewDialog.value = false;
	}

	async function confirmReview() {
		if (!activeDiagramName.value) return;
		reviewStage.value = "loading";
		try {
			const url =
				reviewKind.value === "doctypes"
					? "/api/method/processa.api.production_review.review_doctypes"
					: "/api/method/processa.api.production_review.review_workflow_objects";
			const response = await frappeRequest({
				url,
				method: "GET",
				params: { model_name: activeDiagramName.value },
			});
			const data = response.message || response;
			reviewChanges.value = data.changes || [];
			reviewStage.value = data.has_changes ? "diff" : "empty";
		} catch (err) {
			showReviewDialog.value = false;
			const msg =
				err.messages && err.messages.length
					? err.messages.join("\n")
					: err.message || "Comparison failed.";
			pc.showNotification("Review failed", msg, "red", true);
		}
	}

	async function runSync() {
		if (!activeDiagramName.value) return;
		reviewStage.value = "syncing";
		try {
			const url =
				reviewKind.value === "doctypes"
					? "/api/method/processa.api.production_review.sync_doctypes"
					: "/api/method/processa.api.production_review.sync_workflow_objects";
			const response = await frappeRequest({
				url,
				method: "POST",
				params: { model_name: activeDiagramName.value },
			});
			reviewResult.value = response.message || response;
			reviewStage.value = "result";
		} catch (err) {
			const msg =
				err.messages && err.messages.length
					? err.messages.join("\n")
					: err.message || "Sync failed.";
			reviewResult.value = { error: msg };
			reviewStage.value = "result";
		}
	}

	Object.assign(pc, {
		isBaInstance,
		isProductionInstance,
		syncingLabel,
		reviewTitle,
		reviewIntro,
		reviewEmptyMessage,
		loadProductionReviewSettings,
		openReview,
		closeReview,
		confirmReview,
		runSync,
	});
}
