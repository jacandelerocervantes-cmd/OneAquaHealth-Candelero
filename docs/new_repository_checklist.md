# Creating the new repository from scratch

The plan is a NEW repository with one initial commit made from the current working tree, so the old history
(which holds the unlicensed implementation-guide archive) never travels. Nothing here is run by an agent: the
commit, the remote and the push are the maintainer's.

## 1. Prepare a clean copy

1. Copy the project folder to a new location **without** the `.git` folder, or run `git init` in an empty folder
   and copy the files in. Leave out what is local only: `.venv`, `data/` contents other than `.gitkeep` and
   `README.md`, caches (`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.hypothesis`, `.coverage`), `node_modules`,
   `.env`, the organisers' slides and everything under `reference/` except `CHECKSUMS.sha256`.
2. The three variables (`OAH_ENABLE_DOCS`, `OAH_TRUSTED_PROXIES`, `OAH_LLM_MODEL`) are already in the maintainer's
   environment example file (confirmed 2026-09-29); nothing to add.
3. Set `OAH_LLM_MODEL` in your own `.env` if it still names an older model.

## 2. Check before the first commit

```bash
git init
git add -A
git ls-files | grep -E "^ig/oah/|^reference/.*\.(zip|pdf)$|OneAquaHealth_hackathon_session_|(^|/)\.env$" ; echo "must print nothing above"
git status --short | head -20
python -m pytest -q tests/portability
```

`tests/portability/test_no_forbidden_tracked_files.py` performs the same check and fails if a forbidden file is
tracked. Use `git commit -m "Initial commit"` (with `-m`, so no editor opens) or a message file.

## 3. First push

1. Create the remote repository on GitHub, add it as `origin` and push.
2. Read the first run of `.github/workflows/ci.yml`. It has never run: the suite in a clean clone has not been
   verified (no `ig/` or `reference/` archive is present), and Linux compatibility is unverified (the job uses
   Windows). `pip-audit` is advisory until `pytest` is upgraded to 9.0.3.
3. Keep the old local repository private or delete it; never push it.

## 4. Ask the guide's maintainers to declare a licence

Open an issue at `https://github.com/hl7-eu/oah/issues` (the person publishing it decides the wording; a draft):

> **Title:** Please declare a licence for this repository
>
> Hello, and thank you for the OneAquaHealth implementation guide. We are using it as a reference for a project
> in the OneAquaHealth hackathon (profile URLs, constraints derived from the profiles, validation against them).
> The repository has no LICENSE file, and `sushi-config.yaml` carries a commented-out `# license: CC0-1.0` line, so
> the terms of reuse are unclear to downstream users. Could you add a licence file and set the `license` element
> in `sushi-config.yaml`, for example CC0-1.0 if that was the intention? Until then we only read and reference the
> guide and do not redistribute it. Thank you.

When they answer, record the licence and date in `SOURCES.yaml` (entry `hl7-eu/oah`) and in the ledger.

## 5. What stays out and why

`docs/third_party_dependencies.md` lists every dependency, where it is cited and its licence status. Third-party
material without a stated licence (the guide, the organisers' slides) stays on disk, cited, and out of git.
