# Release Management & Versioning

This project uses **fully automated releases** driven by
[Conventional Commits](https://www.conventionalcommits.org/) and
[python-semantic-release](https://python-semantic-release.readthedocs.io/).

Every merge to `main` is analysed by the release workflow. If any commit in
the range since the last tag warrants a version bump, the workflow:

1. Computes the next version per [Semantic Versioning 2.0](https://semver.org/).
2. Updates `pyproject.toml:project.version`.
3. Regenerates `CHANGELOG.md`.
4. Commits the version bump as `chore(release): vX.Y.Z [skip ci]`.
5. Creates an annotated git tag `vX.Y.Z`.
6. Publishes a GitHub Release with auto-generated notes.

No human ever edits `pyproject.toml` version or `CHANGELOG.md` directly.

---

## Semantic versioning policy

Given **MAJOR.MINOR.PATCH**, for *this* project:

| Change | Bump |
|---|---|
| Breaking change to the public HTTP API (path, request schema, response schema) | MAJOR *(MINOR while on 0.x — see pre-1.0 note)* |
| Breaking change to Pydantic models in `src/models.py` (removed/renamed field, narrowed type) | MAJOR *(MINOR while on 0.x)* |
| Breaking change to LangGraph `GraphState` keys or routing contract | MAJOR *(MINOR while on 0.x)* |
| Removal of a CLI slash command or change in its arguments | MAJOR *(MINOR while on 0.x)* |
| New HTTP endpoint, new CLI command, new model field (additive) | MINOR |
| New transaction category, new goal type, new ingestion source | MINOR |
| Pinned LLM model-id upgrade (e.g. `claude-opus-4-7` → a later Claude major) | MINOR |
| Bug fix that restores documented behaviour | PATCH |
| Performance improvement with no behaviour change | PATCH |
| Prompt-tuning fix that corrects wrong LLM outputs | PATCH |
| Dependency bump with no observable behaviour change | PATCH |
| Docs, tests, CI, style, refactor with no behaviour change | *no release* |

### Pre-1.0 behaviour

While the version is `0.x.y`, `major_on_zero = false` is configured in
`pyproject.toml`. Breaking changes downgrade a bump that would otherwise be
MAJOR to MINOR. The move to `1.0.0` is a deliberate, human-triggered release
(see *Manual release* below) once the public API is considered stable.

---

## Commit format

```
<type>(<scope>)!?: <short summary>

<body — optional>

<footer — optional>
```

### Types → release impact

| Type | Meaning | Bump |
|---|---|---|
| `feat` | New user-visible capability | MINOR |
| `fix` | Bug fix | PATCH |
| `perf` | Performance improvement | PATCH |
| `docs` | Documentation only | none |
| `chore` | Tooling, deps, housekeeping | none |
| `refactor` | Internal change, no behaviour delta | none |
| `test` | Test-only change | none |
| `ci` | CI/workflow change | none |
| `build` | Build-system change | none |
| `style` | Formatting/whitespace | none |

### Breaking changes

Two equivalent ways:

1. Add `!` after the type or scope: `feat(api)!: rename /chat → /ask`.
2. Add a `BREAKING CHANGE:` footer paragraph explaining the migration:

```
feat(models): drop legacy `raw_text` field

BREAKING CHANGE: Transaction.raw_text removed. Callers relying on it must
source raw rows from the source CSV/PDF directly.
```

### Examples

```
feat(ingestion): add currency field to Transaction model
fix(agent): strip markdown fences from goal CSV LLM response
perf(vector-store): filter metadata before embedding search
docs(readme): add pre-1.0 stability note
chore(deps): bump langgraph to 0.3.0
refactor(analyser): extract category-rollup helper
feat(api)!: rename /chat to /ask
```

### Local commit template

Enable the included template so the format is prompted on every `git commit`:

```bash
git config commit.template .gitmessage
```

---

## Workflows

### Automated release (default path)

1. Developer opens a PR targeting `main`. CI runs lint + tests (`.github/workflows/ci.yml`).
2. PR merges to `main` (squash merge with a conventional-commit title is recommended).
3. `.github/workflows/release.yml` fires.
4. `python-semantic-release` inspects commits since the last tag.
5. If any commit warrants a bump, it executes the 6-step release listed at the top of this doc.
6. If no commit warrants a bump (e.g. only `docs:`/`chore:`), the workflow is a no-op.

No manual action, no version prompt, no CHANGELOG editing.

### Dry run (preview next version locally)

```bash
make release-dry
```

This prints what the next version would be and what the CHANGELOG entry
would look like, without committing, tagging, or pushing.

### Manual release (emergency / first 1.0.0 cut)

Use this only when the automated path is not appropriate — e.g. promoting
pre-1.0 to `1.0.0`, or releasing from a hotfix branch.

```bash
export GH_TOKEN=$(gh auth token)        # GitHub personal access token
make release-local                       # or run the semantic-release commands directly
```

For a forced version (e.g. the 1.0.0 cut):

```bash
uv run semantic-release version --major
git push --follow-tags
```

### Pre-releases

Create a branch named `rc/*` or `beta/*` for pre-release work. To add
pre-release support, extend `[tool.semantic_release.branches]` in
`pyproject.toml` — not configured by default to keep the happy path simple.

---

## Required repository setup (one-time)

The release workflow needs:

- Default branch named `main`.
- Workflow `permissions: contents: write` — configured inline in
  `.github/workflows/release.yml`.
- Repository setting **Settings → Actions → General → Workflow permissions**
  set to **Read and write permissions**, and
  **Allow GitHub Actions to create and approve pull requests** enabled.

No personal access token is needed — the built-in `GITHUB_TOKEN` is enough
for tags, commits, and GitHub releases.

### Optional: protect `main`

Add a branch-protection rule requiring CI to pass before merge. The release
workflow's own `chore(release):` commit must be allowed to bypass this
(either via admin bypass or by keeping the `[skip ci]` tag in the commit
message — already configured).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Release workflow runs but no release is produced | All commits since last tag are non-releasing types (`docs`, `chore`, etc.) | Expected — nothing to release. |
| Workflow fails with `fatal: could not read Username` | Missing `token:` on the checkout step, or workflow permissions not set to read/write | Confirm `.github/workflows/release.yml` checkout step passes `token: ${{ secrets.GITHUB_TOKEN }}`, and repo Actions permissions are read/write. |
| Version in `pyproject.toml` is out of sync with the latest tag | Someone edited the version manually, bypassing the bot | Revert the manual change; let the next release re-sync. Tag is the source of truth. |
| CHANGELOG has duplicate entries after a manual edit | Automated regeneration collided with a hand edit | Revert the hand edit. `CHANGELOG.md` is fully owned by `python-semantic-release`. |
| Bot creates infinite release loop | The `[skip ci]` tag was stripped from the release commit message | Confirm `commit_message` in `pyproject.toml` still contains `[skip ci]`. |

---

## What this replaces

Before v0.1.0, the project had no release tooling — version was manual in
`pyproject.toml`, no CHANGELOG, no tags. The configuration in this document
is the single source of truth going forward. Do not introduce parallel
tools (bump2version, commitizen, standard-version, etc.) without removing
`python-semantic-release` first.
