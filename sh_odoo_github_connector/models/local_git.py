"""Synchronous local Git operations; no background service or job queue."""
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class GitError(Exception):
    pass


def run_repository(operation, destination, repository, branch, token, timeout=90):
    if operation not in ('clone', 'pull'):
        raise GitError('Unsupported repository operation.')
    raw = Path(destination).expanduser()
    if not raw.is_absolute() or any(ord(c) < 32 for c in destination):
        raise GitError('Enter an absolute Clone Path on the Odoo machine.')
    path = raw.resolve()
    if path in (Path('/'), Path.home()):
        raise GitError('Choose a dedicated repository folder, not the filesystem root or home directory.')
    if not branch or branch.startswith('-') or any(ord(c) < 32 for c in branch):
        raise GitError('Select a valid branch.')
    if not token:
        raise GitError('Connect your GitHub token in Settings first.')
    if operation == 'clone' and path.exists():
        raise GitError('Clone Path already exists. Choose an unused directory, or use Pull Latest for an existing matching clone.')
    if operation == 'pull' and not (path / '.git').is_dir():
        raise GitError('No Git clone exists at this path. Click Clone Repository first.')
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / ('.sh-odoo-' + hashlib.sha256(str(path).encode()).hexdigest()[:16] + '.lock')
    # Lock is held across the complete operation, including directory installation.
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GitError('Another clone or pull is using this path. Wait for it to finish.') from None
        if operation == 'clone' and path.exists():
            raise GitError('Clone Path now exists; no files were overwritten.')
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='sh-git-auth-') as auth:
            askpass = Path(auth) / 'askpass'
            askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) printf "%s\\n" x-access-token;; *) printf "%s\\n" "$SH_GITHUB_TOKEN";; esac\n')
            askpass.chmod(0o700)
            env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                   'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': str(askpass), 'SH_GITHUB_TOKEN': token}
            def git(*args):
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise GitError('Git operation exceeded 90 seconds. Inspect the repository before retrying; use a terminal for large repositories.')
                # Output stays local, bounded by a temporary file rather than memory. Never persist Git output containing credentials.
                with tempfile.TemporaryFile() as output:
                    process = subprocess.Popen(['/usr/bin/git', *args], env=env,
                        stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
                    try:
                        result = process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        raise GitError('Git timed out. Inspect the clone before retrying; use a terminal for large repositories.') from None
                    finally:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                    output.seek(0, 2)
                    size = output.tell()
                    output.seek(max(0, size - 8000))
                    text = output.read().decode('utf-8', errors='replace')
                if result:
                    # Categorize without returning arbitrary stderr (which may include credentials from existing Git configuration).
                    if 'Authentication failed' in text or 'could not read' in text or 'Repository not found' in text or 'error: 403' in text or 'error: 401' in text:
                        raise GitError('GitHub denied Git access. Check the token repository selection and Contents read permission.')
                    raise GitError('Git refused the operation. Check branch access, repository state and filesystem permissions. No forced reset was attempted.')
                return text.strip()
            git('check-ref-format', '--branch', branch)
            url = 'https://github.com/' + repository + '.git'
            if operation == 'clone':
                with tempfile.TemporaryDirectory(prefix='.sh-clone-', dir=path.parent) as staging:
                    checkout = Path(staging) / 'repository'
                    git('clone', '--single-branch', '--branch', branch, '--', url, str(checkout))
                    if path.exists():
                        raise GitError('Clone Path appeared during cloning. No files were overwritten.')
                    checkout.rename(path)
            else:
                if git('-C', str(path), 'rev-parse', '--show-toplevel') != str(path):
                    raise GitError('Clone Path must be the repository root.')
                if git('-C', str(path), 'remote', 'get-url', 'origin') != url:
                    raise GitError('The existing clone belongs to a different repository or uses a different origin URL.')
                if git('-C', str(path), 'status', '--porcelain', '--untracked-files=all'):
                    raise GitError('Local edits or untracked files exist. Commit or move them before pulling; your files were preserved.')
                if git('-C', str(path), 'symbolic-ref', '--short', 'HEAD') != branch:
                    raise GitError('The local branch differs from the selected branch. Use a separate Clone Path.')
                git('-C', str(path), 'fetch', 'origin', 'refs/heads/' + branch)
                try:
                    git('-C', str(path), 'merge-base', '--is-ancestor', 'HEAD', 'FETCH_HEAD')
                except GitError:
                    raise GitError('Local commits are ahead or diverged. Pull requires a fast-forward; no reset was performed.') from None
                git('-C', str(path), 'merge', '--ff-only', '--no-overwrite-ignore', 'FETCH_HEAD')
            sha = git('-C', str(path), 'rev-parse', 'HEAD')
            return sha, 'Repository ready at %s\nBranch: %s\nCommit: %s' % (path, branch, sha)
