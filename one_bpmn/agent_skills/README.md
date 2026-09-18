# Agent skills

Skill folders seeded into the `AI Skill` doctype by
`patches/v1_0/seed_specialist_agent_skills.py` and enabled on the specialist
agent configurations.

Each folder holds a `SKILL.md` with YAML frontmatter (`name`, `description`) and
a markdown body. Every other file in the folder becomes an `AI Skill Resource`
row named by its path relative to the folder, so a body that links to
`references/controllers.md` names the resource the model loads.

The Frappe and mobile skills are copies of `ONE-F-M/ai-instructions`
(`frappe-erpnext-agent/.agents/skills` and
`mobile-app-agent/.agents/skills`). Bodies and reference files are unchanged.
Only the frontmatter description carries an added sentence for the trigger and
one for the anti-trigger, which `AI Skill` validation requires. Update those
folders from that repository when it changes, and keep the two sentences.
