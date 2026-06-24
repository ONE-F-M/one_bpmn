# Review and Retro Workflow

Run this workflow at the end of each conversation to review the session and generate a retrospective report.

## Steps

### 1. Count and Categorize Prompts

Review the entire conversation history. Classify each user prompt (message) into one of two categories:

- **Planning Prompt:** User messages about approach, design, requirements, reviewing plans, asking clarifying questions, discussing architecture, or requesting research/analysis.
- **Execution Prompt:** User messages requesting code changes, implementation, debugging, testing, verification, deployments, or reviewing final output.

Count the total number of prompts in each category.

### 2. Log Prompt Counts

List each user prompt with its classification. Use this format:

| # | Prompt Summary (first ~15 words) | Category |
|---|----------------------------------|----------|
| 1 | "I want to create a new ..." | Planning |
| 2 | "Fix the failing test in ..." | Execution |

Then provide the totals:

- Planning Prompts: X
- Execution Prompts: X
- Total Prompts: X

### 3. Analyze Prompt Quality

Review the user's prompts and identify patterns. For each pattern found, provide a concrete suggestion. Focus on:

- Vague prompts that caused extra back-and-forth (suggest how to make them specific)
- Missing context that forced follow-up questions (suggest what context to include upfront)
- Scope creep where one prompt tried to do too many things (suggest how to split)
- Redundant prompts that repeated earlier instructions (suggest how to avoid)
- Prompts that could be combined into fewer, more efficient messages

### 4. Generate Retro Report

Output a single report with these sections:

## Conversation Retro Report

Date: YYYY-MM-DD
Conversation Title: \<title from conversation\>

### Prompt Summary

- Planning Prompts: X
- Execution Prompts: X
- Total Prompts: X

### Prompt Log

\<table from step 2\>

### What Went Well

\<list things the user did effectively in their prompts\>

### Improvement Suggestions

\<numbered list of specific, actionable suggestions to reduce prompt count and improve prompt quality\>

### Estimated Prompt Savings

\<estimate how many fewer prompts could have achieved the same outcome, with brief justification\>
