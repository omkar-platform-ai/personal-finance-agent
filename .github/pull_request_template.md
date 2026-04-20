## Summary

<!-- 1-3 bullets describing what this PR does and why -->

## Commit format reminder

This repo uses **Conventional Commits** for fully automated releases. Your
squash-merge title (and any unsquashed commits) should follow:

- `feat: ...` → MINOR release
- `fix: ...` → PATCH release
- `perf: ...` → PATCH release
- `docs:` / `chore:` / `refactor:` / `test:` / `ci:` / `build:` / `style:` → no release
- `feat!:` or `BREAKING CHANGE:` footer → MAJOR release (MINOR while on 0.x)

Policy and examples: [docs/RELEASING.md](../docs/RELEASING.md).

## Test plan

- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] Manually verified: <describe>

## Checklist

- [ ] Commits follow conventional-commits format
- [ ] No direct edits to `CHANGELOG.md` or the version in `pyproject.toml` (both are bot-owned)
- [ ] `docs/PRD.md` updated if this changes product scope
