# SH Odoo GitHub Connector

Version 20.0.5.2.0 — GitHub management with direct local cloning and pulling.
No deployment worker, worker key, queue setup, YAML file or separate service is required.

## Simple setup

1. Restart Odoo and upgrade **SH Odoo GitHub Connector** in Apps.
2. Open **Settings → GitHub Connector**. Enter your GitHub token and click **Connect & Sync**.
3. Open **GitHub → Repositories** and select a repository.
4. Enter **Clone Path**: the full destination folder for that repository, for example:

   ```
   /home/shuhaife/Desktop/odoo20/custom_addons/Odoo_18_tutorial
   ```

5. Set **Clone Branch** if you want a different branch from the repository default. For your
   tutorial repository you can enter `netscale`.
6. Save, then click **Clone Repository**. The button runs Git directly on the Odoo machine.
7. Use **Pull Latest** to fetch and fast-forward the same clone later.

Every repository has its own Clone Path and optional Clone Branch. There is no global clone
root to configure. The path is the complete repository directory, not just its parent. The
Odoo operating-system user needs permission to create it, and `/usr/bin/git` must be installed.
When Odoo runs on a server, the path refers to the server, not your browser's computer.

The form shows the local commit, last successful update time and operation result. Clone/Pull
run synchronously: the request waits for Git to finish. Operations have a 90-second bound;
configure an adequate Odoo/proxy request timeout and use a terminal for very large repositories.

## What happens to existing files

- Clone refuses an existing destination and prepares new clones in a temporary sibling folder.
- Pull verifies the origin repository and selected branch.
- Pull refuses local edits, untracked files, and local commits that are ahead or divergent.
- Updates are fast-forward only. No hard reset, force pull or automatic deletion is performed.
- A filesystem lock prevents simultaneous operations on the same destination.
- Git credentials are supplied temporarily through an askpass helper; the token is not saved
  in the repository URL or command arguments.

Clone/Pull update source code only. They do not install addons, update an Odoo database, or
restart an Odoo service. Add the directory containing the addon folders to `addons_path`, restart
Odoo, update the Apps list, then install or upgrade the intended modules separately. If modules
are inside an `addons/` subdirectory, use that directory in `addons_path`.

## GitHub token permissions

Use a fine-grained token limited to the intended repositories:

| Feature | Permission |
| --- | --- |
| Clone, pull, branches and commits | Contents: Read |
| Create/edit/delete files or branches | Contents: Read and write |
| Pull request creation, editing and reviews | Pull requests: Read and write |
| Merge pull requests | Contents: Read and write; repository rules still apply |
| Issues and comments | Issues: Read and write |
| Repository administration | Administration: Read and write where required |

An organization may require approval or SSO authorization. A token that can list repositories
may still lack Contents permission, producing HTTP 403 for branch access or cloning.

The token is stored in Odoo's database under administrator-only Settings access. Masking is not
encryption; protect the database and its backups. Connector administrators may perform GitHub
changes using this shared token. Operators refresh/read data; viewers only read it.

## GitHub management

Use **Refresh Repository** to load branches and recent commits, pull requests and issues.
Use **GitHub Action** to choose an operation:

- Repositories: create, edit description, archive/unarchive, delete.
- Branches: create, rename, delete non-default branches.
- Files: create, edit or delete UTF-8 text files with a new commit (up to 500 KB).
- Pull requests: create/draft, edit, close/reopen, comment, review, merge/squash/rebase.
- Issues: create, edit, close/reopen, comment.

Load and review file/PR details before updating files or merging. Changes use the reviewed SHA
so conflicting updates can be rejected. Deleting repositories/branches requires typing the target.
**Action History** records GitHub mutation requests and their results; uncertain network outcomes
are not automatically retried. Check GitHub before submitting another action.

Refresh loads all branches and up to the latest 100 entries per other endpoint. Cached older
records remain; use GitHub for complete history. Releases, collaborator administration, bulk
Git pushes and binary-file editing are outside this connector's scope.

## Upgrade from the worker-based versions

Existing repositories, GitHub action history and cloned files are preserved. When one old
project maps unambiguously to a repository, its configured clone path and branch are copied
to that repository. With multiple old projects for the same repository, select the desired
path manually instead of guessing.

Worker Settings and worker endpoints are removed. Old queued runs are cancelled, and active
runs are marked for inspection. Historical pipeline records remain available in developer mode
under **Old Pipeline History**; they do not execute anything. Worker-created directories and
clones are not deleted.

The upgrade requests a cooperative stop for a worker created through the previous Settings
buttons, if its managed directory is accessible. An externally configured service must be
stopped separately. Inspect the server if an old deployment was in progress during upgrade.
Automated testing and service deployment controls have been retired in this simplified version.

## Validation

Tests exercise real local Git clone and fast-forward pull, dirty-tree and divergent-history
refusals, existing-directory preservation, path permissions and immediate button execution.
Retained GitHub management tests use mocked API calls. No real repository is mutated during tests.
