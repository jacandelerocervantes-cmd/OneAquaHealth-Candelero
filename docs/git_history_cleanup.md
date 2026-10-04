# Removing the unlicensed IG archive from git history

> **Only needed if this repository is kept.** The plan is to publish a NEW repository started from scratch
> (one initial commit made from the current working tree, without this `.git` folder). Then the old history
> never travels and none of the steps below are required. Before that first commit, check that the two
> paths stay out of it: `git ls-files | grep -E "^ig/|oah-master"` must print nothing (both are gitignored).
> Keep the old local repository private, or delete it once it is no longer needed.

Commit `98a7b63` contains `ig/oah/` (82 files) and `reference/oah-master.zip`, the hl7-eu/oah archive whose
licence is not declared (see `SOURCES.yaml`). The later commit deletes them from the tree, but history keeps
them. This repository has no remote yet, so history can be rewritten safely. **Do this before the first push.**
An agent does not run it: it rewrites every commit and is your decision.

The two CC-BY Zenodo PDFs under `reference/` and `reference/CHECKSUMS.sha256` stay in history: their licence
allows it and they are attributed in `SOURCES.yaml`.

1. Make a backup that can undo everything (a bundle outside the repository):

   ```bash
   git bundle create ../OneAquaHealth-before-cleanup.bundle --all
   ```

2. Rewrite every branch, removing only the two paths:

   ```bash
   git filter-branch --force --index-filter "git rm -r --cached --ignore-unmatch ig/oah reference/oah-master.zip" --prune-empty -- --all
   ```

3. Drop the backup refs that filter-branch leaves and compact the repository:

   ```bash
   git for-each-ref --format="%(refname)" refs/original/ | xargs -n 1 git update-ref -d
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   ```

4. Check that nothing remains:

   ```bash
   git log --all --oneline -- ig/oah reference/oah-master.zip   # must print nothing
   git count-objects -vH
   ```

The local copies of `ig/oah/` and `reference/oah-master.zip` were deleted from disk on 2026-09-29 (restore steps in `docs/environment_setup.md`); the
commit hashes change, so do this only while no one else has cloned the repository. Keep the bundle until you
are satisfied, then delete it.
