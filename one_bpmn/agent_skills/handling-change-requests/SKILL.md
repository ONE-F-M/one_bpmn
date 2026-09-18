---
name: "handling-change-requests"
description: "How to act when a work order names an existing pull request, so review comments are answered on the same branch and the same pull request is updated. Use this skill when the instruction names a pull request or says the work item is in Changes Requested. Do NOT use it for new work that has no pull request yet."
---

# Answering a review

A named pull request means the work exists and a reviewer has asked for changes.
Your job is those changes, nothing else.

## Order

1. `read_pull_request`. The comments that asked for changes are the whole job.
2. `read_work_item` for anything the comments assume.
3. Start from the same branch the pull request is on. Never open a second branch,
   because a second branch makes a second pull request and the review is lost.
4. Fix exactly what each comment asks. One comment, one change.
5. `run_tests`, then `open_pull_request` again. It updates the existing pull
   request because the branch is the same.

## Rules

- Do not redo work the reviewer did not question, however much you would write it
  differently.
- Do not answer a comment in prose and leave the code alone.
- If a comment asks for something you believe is wrong, make the change the
  smallest way that satisfies it and say your concern in the summary.
- If a comment is unclear, say which comment and what you assumed. Do not guess
  silently.

## The summary

List each comment and what you did about it. A reviewer reading it should be able
to tick their own comments off without opening the diff.
