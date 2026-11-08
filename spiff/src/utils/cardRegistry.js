// Copyright (c) 2026, one-fm and contributors
// Card registry (WI-001673): contract event name → card component.
//
// The registry is the ONLY coupling between events and rendering: the panel
// looks a CUSTOM event's name up here; an unregistered onefm.* name renders
// the panel's safe fallback (and fails the WI-001680 conformance build).
// onefm.choice / onefm.conversation_title / onefm.mode_transition are panel
// chrome, deliberately NOT cards.
import DataTableCard from "@/components/Chat/Cards/DataTableCard/DataTableCard.vue";
import DiagramPreviewCard from "@/components/Chat/Cards/DiagramPreviewCard/DiagramPreviewCard.vue";
import DocTypeSchemaCard from "@/components/Chat/Cards/DocTypeSchemaCard/DocTypeSchemaCard.vue";
import LuCrusherResultCard from "@/components/Chat/Cards/LuCrusherResultCard/LuCrusherResultCard.vue";
import ProposalCard from "@/components/Chat/Cards/ProposalCard/ProposalCard.vue";
import ScriptDiffCard from "@/components/Chat/Cards/ScriptDiffCard/ScriptDiffCard.vue";
import TestCaseCard from "@/components/Chat/Cards/TestCaseCard/TestCaseCard.vue";

export const cardRegistry = {
	"onefm.proposed_config": ProposalCard,
	"onefm.proposed_update": ProposalCard,
	"onefm.script_diff": ScriptDiffCard,
	"onefm.test_cases": TestCaseCard,
	"onefm.bpmn_preview": DiagramPreviewCard,
	"onefm.doctype_schema": DocTypeSchemaCard,
	"onefm.table": DataTableCard,
	// WI-001678: LuCrusher's own result panels. Registered centrally rather
	// than owned by the one-ai page, so every host that can run the agent
	// (the page, the desk Chat dialog) renders its results the same way.
	"onefm.lucrusher_result": LuCrusherResultCard,
};
