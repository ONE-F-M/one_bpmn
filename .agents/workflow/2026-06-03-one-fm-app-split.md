# Conversation Retro Report

Date: 2026-06-10
Conversation Title: One-FM App Split — Monolith to 5 Domain Apps

## Prompt Summary

- Planning Prompts: 8
- Execution Prompts: 4
- Total Prompts: 12

## Prompt Log

| # | Prompt Summary (first ~15 words) | Category |
|---|----------------------------------|----------|
| 1 | "Analyze the one_fm app and propose how to split it into smaller apps." | Planning |
| 2 | "Generate two options: conservative 7-app and aggressive 15-app split." | Execution |
| 3 | "Map all items to APQC PCF v7.3.1 categories." | Execution |
| 4 | "Generate the Excel with target app and component type columns." | Execution |
| 5 | "Review: the platform app is too big. Can we split it further?" | Planning |
| 6 | "Try a process-based split using the workbook data instead." | Planning |
| 7 | "Generate a business-segment-based split as a third option." | Planning |
| 8 | "Wait — let's converge on 5 apps instead. Merge Assets and Procurement into SCM." | Planning |
| 9 | "Update the Excel and regenerate reports with Component Type column." | Execution |
| 10 | "Where should Accommodation live? GRD or SCM? Let's discuss." | Planning |
| 11 | "Run this by Gemini for feedback on the structure." | Planning |
| 12 | "Apply Gemini's feedback — move HR www pages out of platform, rename supply → SCM." | Planning |

## What Went Well

- **Thorough exploration of multiple angles:** Code-level analysis (7 vs 15 apps), process-workbook analysis (5 vs 12 apps), and business-segment analysis were all generated before converging — left no reasonable stone unturned
- **Convergence decision was well-timed:** After exploring 3 different approaches, you committed to the 5-app structure instead of continuing to iterate
- **Used external validation:** Running the proposal past Gemini was a good check before finalizing
- **Self-correction on platform size:** Recognizing platform's 981 items needed a Component Type breakdown was a smart transparency move
- **Explicit naming decisions:** Renaming one_fm_supply → one_fm_SCM and debating Accommodation placement showed domain awareness

## Improvement Suggestions

1. **Switch from analysis to execution sooner.** 3 split approaches, Gemini feedback, Excel normalization — the analysis phase consumed ~10 prompts before any scaffold command was given. A working proof-of-concept (move 1 clean module like Accommodation) after prompt #4 would have validated the approach faster than 8 more planning cycles.

2. **One Excel, not three formats.** The same data was generated as .xlsx, .md, .html, and .pdf reports across multiple split proposals. A single source-of-truth Excel updated iteratively would have saved report-regeneration overhead.

3. **Gemini feedback should have been gated earlier.** Running analysis past a second model is useful, but prompting #11/#12 came after the structure was already finalized. If Gemini feedback was planned, it should have been solicited earlier (around prompt #2 or #4) to avoid rework.

## Estimated Prompt Savings

**4-5 prompts saved** (30-40% reduction) by:
- Skipping overlapping report format generation (HTML + PDF were redundant given the .md and .xlsx)
- Soliciting Gemini feedback earlier, before converging on the final structure
- Scaffolding the first target app after prompt #4 instead of continuing to iterate on split proposals

The core decision (5-app structure with platform/foundation) was solid — the overhead was in generating multiple redundant proposal formats and over-validating before any code was touched.
