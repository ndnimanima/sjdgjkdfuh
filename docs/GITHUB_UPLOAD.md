# Manual GitHub upload for Rozaneh v1.06

This release package is intended to be extracted and uploaded through GitHub's web UI. The ZIP excludes `.git` history, `.env`, SQLite/runtime data, Python caches, Wrangler cache, and obsolete generated UI screenshots. **Upload the extracted project contents—not the ZIP itself.**

## Upload through GitHub's web UI

1. Download `rozaneh-v1.06-github-upload.zip` and extract it on your computer.
2. Create an empty GitHub repository, or open the existing repository and select the branch you intend to update.
3. Choose **Add file → Upload files** and upload the extracted project files. On an existing repository, matching source files will be replaced. Include hidden files—especially `.gitignore` and `.github/workflows/ci.yml`—if they are not already present.
4. Review the file list before committing. It must not include `.env`, `data/rozaneh.db`, bot tokens, API keys, or generated image-cache files.
5. Enter a clear commit message such as `Release Rozaneh v1.06` and commit the upload in GitHub.
6. If a hosting service is connected to that branch, check its build/deploy status yourself. Keep the existing persistent volume attached; do not reset or delete production data during a code update.

## Important: check old Git history

An earlier version of this repository tracked `data/rozaneh.db`, which can contain authentication sessions and destination credentials. The v1.06 source package excludes the database, but replacing files through GitHub's web UI does **not** erase a previously committed database blob from Git history.

If values in an old database were real, revoke or rotate the affected credentials. If sensitive data was ever committed, use a new clean repository or have an administrator carefully purge it from all history before any history rewrite. Do not upload or publish an old `.git` directory without reviewing it.
