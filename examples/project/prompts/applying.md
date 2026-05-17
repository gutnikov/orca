# Applying Agent

You are an applying agent. Merge this issue's worktree branch into the base
branch cleanly.

## Issue

**Title:** {{ issue.fields.title }}

**Scope Boundary:** {{ issue.fields.scope_boundary }}

## Instructions

### Step 1: Identify Branches

```bash
git branch --show-current    # worktree branch with the implementation
git log --oneline -5
```

The base branch is: **`{{ issue.base_branch }}`**

### Step 2: Merge Base Into Worktree

Resolve conflicts here, not on the base branch:

```bash
git fetch origin
git merge origin/{{ issue.base_branch }}
```

### Step 3: Resolve Conflicts

If there are conflicts:
1. List them: `git diff --name-only --diff-filter=U`
2. For files in your scope, prefer this branch's version
3. For shared files, carefully merge both sides
4. Stage resolved files and complete the merge

### Step 4: Run Hooks

```bash
pre-commit run --all-files    # if available
```

Fix any failures and commit fixes.

### Step 5: Push and Merge

```bash
git push origin HEAD
git checkout {{ issue.base_branch }}
git merge --no-ff <worktree-branch> -m "merge: {{ issue.fields.title }}"
git push origin {{ issue.base_branch }}
```

If push fails, pull and retry:
```bash
git pull --rebase origin {{ issue.base_branch }}
git push origin {{ issue.base_branch }}
```

## Output

Write the result JSON to `{{ result_path }}`:

```json
{{ result_example | tojson(indent=2) }}
```
