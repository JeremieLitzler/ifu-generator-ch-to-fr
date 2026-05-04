Create a pull request from the current branch, evaluate its contents, and merge after human approval.

**Usage:** `/open-pr`

Aborts if the current branch is `main`.

---

## Step 1 — Verify branch

Run:

```bash
rtk git status
```

If the current branch is `main`, stop and tell the user: "Already on main — check out a feature branch first."

---

## Step 2 — Evaluate commits on this branch

Run in parallel:

```bash
rtk git log main..HEAD
rtk git diff main...HEAD
```

From these, extract:

- **Commits**: list of subject lines (most recent first)
- **Files changed**: list with a one-line summary of what changed in each
- **Overall purpose**: one sentence describing what this branch achieves

Present the evaluation to the user in this format:

```
Branch: <branch-name>
Commits (<N>):
  - <subject>
  - …

Files changed:
  - <file> — <what changed>
  - …

Summary: <one-sentence purpose>
```

---

## Step 2b — Human review: evaluation

Ask the user:

> "Does this evaluation look correct? Anything to adjust in the PR title or description before I create it?"

Wait for explicit approval or corrections before proceeding to Step 3. Apply any changes the user requests to the draft title/body.

---

## Step 3 — Create the pull request

Derive a PR title from the branch commits (use the evaluation summary if a single-commit branch, otherwise synthesize from all subjects).

Run:

```bash
rtk gh pr create \
  --title "<derived title>" \
  --body "$(cat <<'EOF'
## Summary

- <bullet per logical change, drawn from the commit list>

## Files changed

- `<file>` — <what changed>

## Test plan

- [ ] All existing tests pass
- [ ] Output CSVs and README verified manually for the target year

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Report the PR URL to the user.

---

## Step 3b — Human review: PR

Show the PR URL and the rendered summary. Ask the user:

> "Does the PR look good? Ready to merge into main?"

Wait for explicit approval before proceeding to Step 4. If the user requests changes to the PR description or needs additional commits, apply them and repeat this step.

---

## Step 4 — Merge and sync local main

Run:

```bash
rtk gh pr merge --rebase --delete-branch
```

Then pull main locally:

```bash
rtk git checkout main && rtk git pull
```

Report the merge commit hash and confirm the branch was deleted.
