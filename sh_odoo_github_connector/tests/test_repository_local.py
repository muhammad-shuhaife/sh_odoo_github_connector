import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.addons.sh_odoo_github_connector.models.local_git import GitError, run_repository


@tagged('post_install', '-at_install')
class TestLocalRepository(TransactionCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / 'source'
        self.origin.mkdir()
        def git(*args):
            return subprocess.check_output(['/usr/bin/git', '-C', str(self.origin), *args], stderr=subprocess.DEVNULL).decode().strip()
        self.git = git
        git('init', '-b', 'main')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (self.origin / 'module.py').write_text('first\n')
        git('add', 'module.py')
        git('commit', '-m', 'Fixture')
        self.destination = self.root / 'clone'
        real_popen = subprocess.Popen
        def popen(args, *a, **kw):
            args = list(args)
            # Replace only network transport; retain real git checkout/status/merge operations.
            if 'clone' in args:
                args[args.index('--') + 1] = str(self.origin)
            if 'fetch' in args:
                args[args.index('fetch') + 1] = str(self.origin)
            return real_popen(args, *a, **kw)
        patcher = patch('odoo.addons.sh_odoo_github_connector.models.local_git.subprocess.Popen', side_effect=popen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def clone(self):
        result = run_repository('clone', str(self.destination), 'org/repo', 'main', 'fixture-token')
        subprocess.check_call(['/usr/bin/git', '-C', str(self.destination), 'remote', 'set-url', 'origin', 'https://github.com/org/repo.git'])
        return result

    def test_clone_and_pull(self):
        sha, log = self.clone()
        self.assertEqual(sha, self.git('rev-parse', 'HEAD'))
        (self.origin / 'module.py').write_text('second\n')
        self.git('commit', '-am', 'Second')
        sha, log = run_repository('pull', str(self.destination), 'org/repo', 'main', 'fixture-token')
        self.assertEqual(sha, self.git('rev-parse', 'HEAD'))
        self.assertEqual((self.destination / 'module.py').read_text(), 'second\n')
        self.assertNotIn('fixture-token', log)

    def test_local_edits_are_preserved(self):
        self.clone()
        (self.destination / 'module.py').write_text('local changes')
        with self.assertRaisesRegex(GitError, 'Local edits'):
            run_repository('pull', str(self.destination), 'org/repo', 'main', 'token')
        self.assertEqual((self.destination / 'module.py').read_text(), 'local changes')

    def test_existing_destination_not_overwritten(self):
        self.destination.mkdir()
        (self.destination / 'keep').write_text('keep')
        with self.assertRaises(GitError):
            run_repository('clone', str(self.destination), 'org/repo', 'main', 'token')
        self.assertEqual((self.destination / 'keep').read_text(), 'keep')

    def test_divergent_history_not_reset(self):
        self.clone()
        (self.destination / 'local.py').write_text('keep')
        subprocess.check_call(['/usr/bin/git', '-C', str(self.destination), 'add', 'local.py'])
        subprocess.check_call(['/usr/bin/git', '-C', str(self.destination), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'Local'], stdout=subprocess.DEVNULL)
        with self.assertRaisesRegex(GitError, 'ahead or diverged'):
            run_repository('pull', str(self.destination), 'org/repo', 'main', 'token')
        self.assertEqual((self.destination / 'local.py').read_text(), 'keep')

    def test_path_and_permissions(self):
        repo = self.env['sh.github.repository'].create({'name':'org/repo', 'owner':'org', 'repository':'repo', 'default_branch':'main'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            repo.clone_path = 'relative/path'
        operator = new_test_user(self.env, login='local_git_operator', groups='sh_odoo_github_connector.group_operator')
        with self.assertRaises(AccessError):
            repo.with_user(operator).action_clone()

    def test_button_executes_immediately(self):
        repo = self.env['sh.github.repository'].create({'name':'org/repo', 'owner':'org', 'repository':'repo', 'default_branch':'main', 'clone_path':str(self.destination)})
        admin = new_test_user(self.env, login='local_git_admin', groups='sh_odoo_github_connector.group_admin')
        self.env['ir.config_parameter'].sudo().set_param('sh_github.token', 'fixture-token')
        previous_count = self.env['sh.github.run'].search_count([])
        with patch.object(self.env.cr, 'commit'):
            result = repo.with_user(admin).action_clone()
        self.assertEqual(result['params']['type'], 'success')
        self.assertTrue((self.destination / '.git').is_dir())
        self.assertTrue(repo.local_commit)
        self.assertEqual(self.env['sh.github.run'].search_count([]), previous_count)
