Start working on a GitHub issue end-to-end: branch, implement, test, commit, push, and open a PR.

**Usage:** `/tackle <issue-number>`

If no issue number is provided, ask the user for one before proceeding.

---

## Step 1 — Fetch the issue

Run:

```bash
rtk gh issue view <issue-number>
```

Extract:

- `title` — the issue title
- `labels` — the first label (used to derive the branch type prefix)
- `body` — the full description (used to understand scope)

---

## Step 2 — Pull main

Make sure the local main branch is up to date before branching:

```bash
rtk git checkout main && rtk git pull
```

---

## Step 3 — Derive the branch name

Map the issue label to a branch prefix using this table:

| Label         | Prefix     |
| ------------- | ---------- |
| `enhancement` | `feat`     |
| `bug`         | `fix`      |
| `refactor`    | `refactor` |
| `ci`          | `ci`       |
| `docs`        | `docs`     |
| `infra`       | `infra`    |

If the label is absent or not in the table, default to `feat`.

Derive a kebab-case slug from the issue **title** (lowercase, words joined with `-`, strip punctuation, max ~40 chars).

Branch name format: `<prefix>/<slug>`

Example: issue #12 titled "Add dividend rounding fix" with label `bug` → `fix/add-dividend-rounding-fix`

Create and check out the branch:

```bash
rtk git checkout -b <branch-name>
```

---

## Step 3b — Research: best approaches

Before writing any code, research how to fulfil the issue requirements. Structure the research in two passes:

**Business perspective** — what problem does this solve? Who is affected? What are the acceptance criteria in plain language? If anything is ambiguous, list the open questions explicitly.

**Technical perspective** — which files, functions, or data structures are involved? What is the minimal change that satisfies the requirements? Are there edge cases or constraints from `CLAUDE.md` that apply?

Keep the output succinct and accurate. If something is unclear, **ask the user directly** rather than assuming.

---

## Step 3c — Human review: specs

Present the research summary (business + technical) and any open questions. Ask the user:

> "Do the specs look right? Any clarifications before I start implementing?"

Wait for explicit approval before proceeding to Step 4. If the user answers questions or requests adjustments, update the research summary and repeat this step.

---

## Step 4 — Implement

Read the issue body carefully. Understand exactly what needs to change before touching any file.

- Follow all rules in `CLAUDE.md` (key implementation rules, cost basis logic, etc.).
- Make only the changes required by the issue — no scope creep.
- Do not add comments unless the _why_ is non-obvious.

### Object Calisthenics (Python)

Apply all nine rules when writing or modifying Python code:

1. **One level of indentation per function** — if a function has an `if` inside a `for`, extract the inner block into a new function.
2. **No `else` keyword** — use early returns or guard clauses instead.
3. **Wrap primitives and strings in domain types** — a bare `str` carrying a ticker symbol or a bare `float` carrying a currency amount should be a named class or `dataclass`.
4. **First-class collections** — a class that holds a collection should hold nothing else; wrap it in its own type with domain-meaningful methods.
5. **One dot per line** — break `a.b.c` into intermediate variables so each line reasons about one thing.
6. **No abbreviations** — `cur` → `currency`, `tx` → `transaction`, `amt` → `amount`, `cnt` → `count`.
7. **Keep entities small** — no function longer than five lines, no class larger than fifty lines, no module with more than ten top-level definitions.
8. **No class with more than two instance variables** — decompose classes that need more state.
9. **No getters or setters** — tell objects what to do rather than asking for their data; prefer methods with domain intent over property accessors.

**Before (violates rules 1 & 2):**

```python
def process(rows):
    result = []
    for row in rows:
        if row["type"] == "BUY":
            if row["amount"] > 0:
                result.append(row)
    return result
```

**After (one indent level, no else):**

```python
def process(rows):
    return [row for row in rows if _is_valid_buy(row)]

def _is_valid_buy(row):
    if row["type"] != "BUY":
        return False
    return row["amount"] > 0
```

Where strict compliance conflicts with Python conventions (e.g. `__init__`, `@property` for computed values, dataclass fields), document the exception inline with a one-line comment starting `# calisthenics-exception:`.

---

### RTK Token Optimization

When running shell commands during implementation or testing, prefer `rtk` equivalents:

| Instead of          | Use                   |
| ------------------- | --------------------- |
| `ls <path>`         | `rtk ls <path>`       |
| `cat/head/tail <f>` | `rtk read <f>`        |
| `grep/rg <pattern>` | `rtk grep <pattern>`  |
| `git …`             | `rtk git …`           |
| `gh …`              | `rtk gh …`            |

Prefer the dedicated Read / Glob / Grep tools over shell commands when available.

---

## Step 4b — Human review: implementation

Present a summary of every file changed and why. Ask the user:

> "Does the implementation look correct? Anything to change before testing?"

Wait for explicit approval before proceeding to Step 5. If the user requests changes, apply them and repeat this step.

---

## Step 5 — Test

After implementing, run relevant tests or verification steps described in the issue body.

- If a `tasks/` file exists for this issue, follow its "Verification steps".
- Run scripts manually with sample data when automated tests are not available.
- Report what was tested and what the result was.

---

## Step 5b — Human review: test results

Report what was run and what each check produced. Ask the user:

> "Do the test results look correct? Ready to commit and push?"

Wait for explicit approval before proceeding to Step 6. If the user requests fixes, apply them, re-run the relevant tests, and repeat this step.

---

## Step 6 — Commit and push

Invoke the `/commit-and-push` skill to stage, commit, and push the branch.

---

## Step 7 — Open a pull request

Run:

```bash
rtk gh pr create \
  --title "<issue title>" \
  --body "$(cat <<'EOF'
## Summary

- <bullet: what changed and why>

Closes #<issue-number>

## Test plan

- [ ] <verification step from the issue or task file>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Report the PR URL to the user.

---

## Step 7b — Human review: PR

Report the PR URL and a brief summary of what it contains. Ask the user:

> "Does the PR look good? Ready to merge?"

Wait for explicit approval before proceeding to Step 8. If the user requests changes, apply them, push, and repeat this step.

---

## Step 8 — Merge the PR

Run:

```bash
rtk gh pr merge <pr-number> --rebase --delete-branch
```

Then pull main locally to stay in sync:

```bash
rtk git checkout main && rtk git pull
```

Report that the PR was merged and the branch deleted.
