import base64
from unittest.mock import Mock, patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

M = 'odoo.addons.sh_odoo_github_connector.models.management'
C = 'odoo.addons.sh_odoo_github_connector.models.connector'


@tagged('post_install', '-at_install')
class TestManagement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='manage_admin', groups='sh_odoo_github_connector.group_admin')
        cls.operator = new_test_user(cls.env, login='manage_operator', groups='sh_odoo_github_connector.group_operator')
        cls.repo = cls.env['sh.github.repository'].sudo().create({'name': 'org/repo', 'owner': 'org',
            'repository': 'repo', 'default_branch': 'main'})

    def wizard(self, operation, **values):
        return self.env['sh.github.action'].with_user(self.admin).create({
            'operation': operation, 'repository_id': self.repo.id, **values})

    def test_operator_cannot_mutate(self):
        wizard = self.wizard('issue_create', title='title')
        with self.assertRaises(AccessError):
            wizard.with_user(self.operator).action_apply()

    def test_delete_requires_exact_confirmation(self):
        wizard = self.wizard('repo_delete', confirmation='repo')
        with self.assertRaises(UserError):
            wizard._request_values()
        wizard.confirmation = 'org/repo'
        self.assertEqual(wizard._request_values(), ('DELETE', '/repos/org/repo', None))

    def test_branch_creation_uses_selected_source(self):
        wizard = self.wizard('branch_create', ref='feature/source', new_branch='feature/new')
        with patch(M + '.github', return_value={'commit': {'sha': 'a' * 40}}) as call:
            method, path, payload = wizard._request_values()
        self.assertIn('feature%2Fsource', call.call_args.args[1])
        self.assertEqual(payload, {'ref': 'refs/heads/feature/new', 'sha': 'a' * 40})
        self.assertEqual(method, 'POST')

    def test_file_update_uses_reviewed_sha(self):
        wizard = self.wizard('file_update', file_path='addon/models.py', ref='main', commit_message='Fix model')
        with self.assertRaises(UserError):
            wizard._request_values()
        with patch(M + '.github', return_value={'type': 'file', 'encoding': 'base64',
                'size': 3, 'content': base64.b64encode(b'old').decode(), 'sha': 'a' * 40}):
            wizard.action_load()
        wizard.content = 'new'
        method, path, payload = wizard._request_values()
        self.assertEqual(payload['sha'], 'a' * 40)
        self.assertEqual(base64.b64decode(payload['content']), b'new')
        wizard.ref = 'different'
        with self.assertRaises(UserError):
            wizard._request_values()

    def test_merge_requires_reviewed_head(self):
        wizard = self.wizard('pr_merge', number=3)
        with self.assertRaises(UserError):
            wizard._request_values()
        with patch(M + '.github', return_value={'title': 'PR', 'body': 'Details', 'head': {'sha': 'b' * 40}}):
            wizard.action_load()
        self.assertEqual(wizard._request_values()[2]['sha'], 'b' * 40)

    def test_audited_mutation_cannot_be_repeated(self):
        wizard = self.wizard('issue_create', title='Test issue', body='Details')
        with patch.object(self.env.cr, 'commit'), patch(M + '.github', return_value={'number': 4}) as call:
            wizard.action_apply()
            self.assertEqual(wizard.attempt_id.state, 'success')
            with self.assertRaises(UserError):
                wizard.action_apply()
        self.assertEqual(call.call_count, 1)

    def test_unknown_mutation_outcome_preserved(self):
        wizard = self.wizard('comment', number=1, body='A comment')
        with patch.object(self.env.cr, 'commit'), patch(M + '.github', side_effect=UserError('Outcome unknown')):
            wizard.action_apply()
        self.assertEqual(wizard.attempt_id.state, 'attention')
        self.assertEqual(wizard.attempt_id.requested_by, self.admin)

    def test_action_payloads(self):
        for operation, expected in [('issue_close','closed'), ('issue_reopen','open'), ('pr_close','closed'), ('pr_reopen','open')]:
            self.assertEqual(self.wizard(operation, number=4)._request_values()[2]['state'], expected)
        self.assertTrue(self.wizard('repo_archive')._request_values()[2]['archived'])
        self.assertFalse(self.wizard('repo_unarchive')._request_values()[2]['archived'])
        self.assertTrue(self.wizard('repo_create', repo_name='new')._request_values()[2]['private'])
        self.assertEqual(self.wizard('pr_create', title='PR', head='feature', base='main')._request_values()[2]['head'], 'feature')
        self.assertEqual(self.wizard('branch_rename', ref='old', new_branch='new')._request_values()[2]['new_name'], 'new')
        self.assertEqual(self.wizard('branch_delete', ref='old', confirmation='old')._request_values()[0], 'DELETE')

    def test_permission_and_rate_limit_diagnostics(self):
        from odoo.addons.sh_odoo_github_connector.models.connector import github
        response = Mock(status_code=403, headers={'X-Accepted-GitHub-Permissions': 'contents=read'})
        with patch(C + '.requests.request', return_value=response):
            with self.assertRaisesRegex(UserError, 'Contents → Read'):
                github(self.env, '/repos/org/repo/branches', token='secret')
        response.headers = {'X-RateLimit-Remaining': '0'}
        with patch(C + '.requests.request', return_value=response):
            with self.assertRaisesRegex(UserError, 'rate limit'):
                github(self.env, '/user', token='secret')

