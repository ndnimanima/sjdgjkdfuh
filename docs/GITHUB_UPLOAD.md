# Clean GitHub upload for Rozaneh v1.04

The clean release package is meant to be extracted and uploaded as source. It deliberately excludes `.git` history, `.env`, SQLite/runtime data, Python caches, Wrangler cache, and obsolete generated UI screenshots.

## Recommended: create a clean GitHub repository

1. Download and extract `rozaneh-v1.04-github-upload.zip` (uploading the ZIP itself to GitHub will only store the ZIP as a file).
2. Create an empty repository on GitHub. Do not initialize it with a README, license, or `.gitignore` because these are already included.
3. From the extracted project directory, run:

   ```bash
   git init -b main
   git add -A
   git diff --cached --check
   git status --short
   git commit -m "Release Rozaneh v1.04"
   git remote add origin https://github.com/OWNER/REPOSITORY.git
   git push -u origin main
   ```

   Replace `OWNER/REPOSITORY` with the destination you control. Review `git status` before committing and make sure no real `.env`, SQLite database, bot token, or API key has been added.

You can also extract the archive locally and use GitHub's **Add file → Upload files** with the extracted files (not the ZIP file).

## Important: do not push the old Git history blindly

An earlier version of this repository tracked `data/rozaneh.db`. The local database contains authentication sessions and destination credentials. The v1.04 working tree now stages that file for removal and ignores future database files, and the clean upload archive contains no database. However, a normal commit does **not** erase a previously committed database blob from Git history.

If any values in that old database were real, revoke/rotate the affected credentials. To publish safely, use the clean archive in a new repository, or have an administrator carefully purge the sensitive file from all history and coordinate the resulting force-push with collaborators. Do not push the existing `.git` history until that review is complete.
