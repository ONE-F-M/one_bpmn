// Copyright (c) 2026, one-fm and contributors
// Card registry (WI-001673): contract event name → card component.
//
// The registry is the ONLY coupling between events and rendering: the panel
// looks a CUSTOM event's name up here; an unregistered onefm.* name renders
// the panel's safe fallback (and fails the WI-001680 conformance build).
// onefm.choice / onefm.conversation_title / onefm.mode_transition are panel
// chrome, deliberately NOT cards.
import DataTableCard from "./DataTableCard.vue";
import DiagramPreviewCard from "./DiagramPreviewCard.vue";
import DocTypeSchemaCard from "./DocTypeSchemaCard.vue";
import LuCrusherResultCard from "./LuCrusherResultCard.vue";
import ProposalCard from "./ProposalCard.vue";
import ScriptDiffCard from "./ScriptDiffCard.vue";
import TestCaseCard from "./TestCaseCard.vue";

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
