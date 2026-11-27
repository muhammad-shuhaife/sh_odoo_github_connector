import logging
import os
from pathlib import Path

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT key, value FROM ir_config_parameter WHERE key IN ('sh_github.worker_home', 'sh_github.clone_root')")
    settings = dict(cr.fetchall())
    home = settings.get('sh_github.worker_home')
    if home:
        try:
            directory = Path(home).expanduser().resolve()
            marker = directory / '.sh-worker-database'
            state = directory / 'state'
            if marker.is_file() and marker.read_text() == cr.dbname and state.is_dir():
                fd = os.open(state / 'stop.request', os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write('stop')
        except OSError:
            _logger.warning('Could not request the old managed worker to stop; stop its service manually.')
    cr.execute("UPDATE ir_config_parameter SET value = NULL WHERE key = 'sh_github.worker_token'")
    cr.execute("""UPDATE sh_github_run SET state = 'cancelled', conclusion = 'cancelled',
        error_message = 'Worker mode removed. Use Clone/Pull on the repository.' WHERE state = 'pending'""")
    cr.execute("""UPDATE sh_github_run SET state = 'error', conclusion = 'interrupted',
        error_message = 'Worker mode removed. Inspect the server/files if this job was running during upgrade.'
        WHERE state IN ('submitted', 'running')""")
    cr.execute("""UPDATE ir_cron SET active = false WHERE id IN
        (SELECT res_id FROM ir_model_data WHERE module = 'sh_odoo_github_connector' AND name = 'cron_github_runs')""")
    # Carry over an unambiguous v4 per-project path; never guess between multiple projects.
    root = settings.get('sh_github.clone_root')
    cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'sh_github_project'")
    columns = {row[0] for row in cr.fetchall()}
    if root and 'clone_subdir' in columns:
        cr.execute("""SELECT r.id, p.owner, p.repository, p.clone_subdir, p.branch
            FROM sh_github_repository r JOIN sh_github_project p
              ON p.owner=r.owner AND p.repository=r.repository
            WHERE r.clone_path IS NULL AND 1=(SELECT count(*) FROM sh_github_project p2
              WHERE p2.owner=r.owner AND p2.repository=r.repository)""")
        for repo_id, owner, repository, subdir, branch in cr.fetchall():
            base = Path(root).expanduser().resolve()
            destination = (base / (subdir or (owner + '/' + repository))).resolve()
            if destination != base and destination.is_relative_to(base):
                cr.execute('UPDATE sh_github_repository SET clone_path=%s, clone_branch=%s WHERE id=%s',
                           (str(destination), branch, repo_id))
