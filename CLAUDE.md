Read [AGENTS.md](AGENTS.md). It is the single set of instructions for this repo.

## Pull requests

Never run `git push` or `gh pr create` directly. Commit your work, then run one of the commands below from the root of this repo. Ask the developer for the work item id and the base branch first; never guess either.

New PR:

```bash
bash .claude/open-pr-via-github-app.sh <work-item-id> <base-branch> --title "<title>" --body-file <file>
```

Follow-up commits to an existing PR (only after the developer approves):

```bash
bash .claude/open-pr-via-github-app.sh --update <work-item-id> <base-branch>
```
