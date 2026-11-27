import base64
import json
import re
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .connector import github, pages, require_group, notice, PREFIX

OPERATIONS = [
    ('repo_create', 'Repository: create'), ('repo_describe', 'Repository: edit description'),
    ('repo_archive', 'Repository: archive'), ('repo_unarchive', 'Repository: unarchive'),
    ('repo_delete', 'Repository: delete'),
    ('branch_create', 'Branch: create'), ('branch_rename', 'Branch: rename'), ('branch_delete', 'Branch: delete'),
    ('file_create', 'File: create and commit'), ('file_update', 'File: edit and commit'), ('file_delete', 'File: delete and commit'),
    ('pr_create', 'Pull request: create'), ('pr_edit', 'Pull request: edit title/body'),
    ('pr_close', 'Pull request: close'), ('pr_reopen', 'Pull request: reopen'),
    ('pr_merge', 'Pull request: merge'), ('pr_review', 'Pull request: submit review'),
    ('issue_create', 'Issue: create'), ('issue_edit', 'Issue: edit title/body'),
    ('issue_close', 'Issue: close'), ('issue_reopen', 'Issue: reopen'),
    ('comment', 'Issue / pull request: add comment'),
]


def dialog(defaults):
    return {'type': 'ir.actions.act_window', 'name': 'GitHub Action',
            'res_model': 'sh.github.action', 'view_mode': 'form', 'target': 'new',
            'context': {'default_' + key: value for key, value in defaults.items()}}


class Repository(models.Model):
    _inherit = 'sh.github.repository'

    description = fields.Text(readonly=True)
    archived = fields.Boolean(readonly=True)
    item_ids = fields.One2many('sh.github.item', 'repository_id', readonly=True)
    branch_ids = fields.One2many('sh.github.branch', 'repository_id', readonly=True)
    synced_at = fields.Datetime(readonly=True)

    def _path(self):
        self.ensure_one()
        return '/repos/%s/%s' % (quote(self.owner, safe=''), quote(self.repository, safe=''))

    def action_open_github(self):
        self.ensure_one()
        self.check_access_rights('read')
        self.check_access_rule('read')
        return {'type': 'ir.actions.act_url', 'url': 'https://github.com/' + quote(self.owner, safe='') + '/' + quote(self.repository, safe=''), 'target': 'new'}

    def action_manage(self):
        self.ensure_one()
        require_group(self.env, 'group_admin')
        self.check_access_rights('read')
        self.check_access_rule('read')
        return dialog({'repository_id': self.id, 'ref': self.default_branch or 'main'})

    def action_sync(self):
        self.ensure_one()
        require_group(self.env, 'group_operator')
        self.check_access_rights('read')
        self.check_access_rule('read')
        # Keep each sync bounded: branches use pagination; other tabs show latest 100.
        repository = github(self.env, self._path())
        branches = list(pages(self.env, self._path() + '/branches'))
        # Fetch everything before changing the cache so partial permission failures leave it intact.
        commits = github(self.env, self._path() + '/commits?per_page=100') if branches else []
        pulls = github(self.env, self._path() + '/pulls?state=all&per_page=100')
        issues = github(self.env, self._path() + '/issues?state=all&per_page=100') if repository.get('has_issues', True) else []
        Branch = self.env['sh.github.branch'].sudo().with_context(active_test=False)
        ids = []
        for row in branches:
            record = Branch.search([('repository_id', '=', self.id), ('name', '=', row['name'])], limit=1)
            values = {'repository_id': self.id, 'name': row['name'], 'commit_sha': row['commit']['sha'], 'active': True}
            if record:
                record.write(values)
            else:
                record = Branch.create(values)
            ids.append(record.id)
        Branch.search([('repository_id', '=', self.id), ('id', 'not in', ids)]).write({'active': False})
        Item = self.env['sh.github.item'].sudo()
        for kind, rows in [('commit', commits), ('pr', pulls), ('issue', issues)]:
            for row in rows:
                if kind == 'issue' and 'pull_request' in row:
                    continue
                number = row.get('number', 0)
                sha = row.get('sha') or (row.get('head') or {}).get('sha')
                key = sha if kind == 'commit' else str(number)
                record = Item.search([('repository_id', '=', self.id), ('kind', '=', kind), ('external_key', '=', key)], limit=1)
                commit = row.get('commit') or {}
                values = {'repository_id': self.id, 'kind': kind, 'external_key': key,
                    'name': (commit.get('message', '').split('\n')[0] if kind == 'commit' else row.get('title')) or key,
                    'number': number, 'sha': sha, 'state': row.get('state') or 'committed',
                    'body': commit.get('message') if kind == 'commit' else row.get('body'),
                    'author': (row.get('user') or row.get('author') or {}).get('login'),
                    'details': False}
                if record:
                    record.write(values)
                else:
                    Item.create(values)
        self.sudo().write({'description': repository.get('description'), 'archived': repository.get('archived', False),
                          'default_branch': repository.get('default_branch'), 'synced_at': fields.Datetime.now()})
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class Item(models.Model):
    _name = 'sh.github.item'
    _description = 'GitHub Commit, Pull Request or Issue'
    _order = 'id desc'

    repository_id = fields.Many2one('sh.github.repository', required=True, ondelete='cascade', readonly=True)
    kind = fields.Selection([('commit', 'Commit'), ('pr', 'Pull Request'), ('issue', 'Issue')], required=True, readonly=True)
    external_key = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, readonly=True)
    number = fields.Integer(readonly=True)
    sha = fields.Char(readonly=True)
    state = fields.Char(readonly=True)
    author = fields.Char(readonly=True)
    body = fields.Text(readonly=True)
    details = fields.Text(readonly=True)

    def action_refresh_details(self):
        self.ensure_one()
        require_group(self.env, 'group_operator')
        self.check_access_rights('read')
        self.check_access_rule('read')
        suffix = {'commit': 'commits/', 'pr': 'pulls/', 'issue': 'issues/'}[self.kind]
        row = github(self.env, self.repository_id._path() + '/' + suffix + quote(self.external_key, safe=''))
        self.sudo().write({'details': json.dumps(row, indent=2, ensure_ascii=False)[:100000],
                          'state': 'merged' if row.get('merged') else row.get('state') or 'committed'})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_manage(self):
        self.ensure_one()
        require_group(self.env, 'group_admin')
        self.check_access_rights('read')
        self.check_access_rule('read')
        if self.kind == 'commit':
            raise UserError(_('Commits are immutable. Use a file action to create a new commit.'))
        return dialog({'repository_id': self.repository_id.id, 'number': self.number,
                       'operation': 'pr_edit' if self.kind == 'pr' else 'issue_edit',
                       'title': self.name, 'body': self.body})

    def action_open_github(self):
        self.ensure_one()
        self.check_access_rights('read')
        self.check_access_rule('read')
        suffix = {'commit': 'commit/', 'pr': 'pull/', 'issue': 'issues/'}[self.kind]
        url = 'https://github.com/' + self.repository_id.name + '/' + suffix + quote(self.external_key, safe='')
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}


class ActionLog(models.Model):
    _name = 'sh.github.action.log'
    _description = 'GitHub Action Audit'
    _order = 'id desc'
    _rec_name = 'operation'

    operation = fields.Selection(OPERATIONS, readonly=True)
    repository_name = fields.Char(readonly=True)
    requested_by = fields.Many2one('res.users', readonly=True)
    target = fields.Char(readonly=True)
    state = fields.Selection([('submitting', 'Submitting / unknown'), ('success', 'Succeeded'),
                              ('attention', 'Check GitHub')], readonly=True)
    message = fields.Text(readonly=True)


class GitHubAction(models.TransientModel):
    _name = 'sh.github.action'
    _description = 'GitHub Action'

    operation = fields.Selection(OPERATIONS, default='branch_create', required=True)
    repository_id = fields.Many2one('sh.github.repository')
    organization = fields.Char(help='Leave empty to create a repository under your GitHub user.')
    repo_name = fields.Char(string='New Repository Name')
    private = fields.Boolean(default=True)
    ref = fields.Char(string='Branch / Source Branch', default='main')
    new_branch = fields.Char(string='New Branch Name')
    number = fields.Integer(string='Issue / Pull Request Number')
    title = fields.Char()
    body = fields.Text(string='Description / Comment')
    head = fields.Char(string='Pull Request Source Branch')
    base = fields.Char(string='Pull Request Target Branch', default='main')
    draft = fields.Boolean()
    merge_method = fields.Selection([('merge', 'Merge commit'), ('squash', 'Squash'), ('rebase', 'Rebase')], default='squash')
    review_event = fields.Selection([('COMMENT', 'Comment'), ('APPROVE', 'Approve'), ('REQUEST_CHANGES', 'Request changes')], default='COMMENT')
    file_path = fields.Char()
    content = fields.Text(string='UTF-8 File Content')
    commit_message = fields.Char()
    loaded_sha = fields.Char(string='Reviewed File / Head SHA', readonly=True)
    loaded_target = fields.Char(readonly=True)
    confirmation = fields.Char(string='Type Repository or Branch Name to Confirm')
    attempt_id = fields.Many2one('sh.github.action.log', readonly=True)
    permission_hint = fields.Char(compute='_compute_permission_hint')

    @api.depends('operation')
    def _compute_permission_hint(self):
        for rec in self:
            if (rec.operation or '').startswith('repo_'):
                rec.permission_hint = 'Repository administration may require Administration write and organization approval.'
            elif (rec.operation or '').startswith('pr_'):
                rec.permission_hint = 'Token permission: Pull requests write; merging also requires Contents write.'
            elif (rec.operation or '').startswith('issue_') or rec.operation == 'comment':
                rec.permission_hint = 'Token permission: Issues write (or Pull requests write for PR comments).'
            else:
                rec.permission_hint = 'Token permission: Contents write. Branch protection rules still apply.'

    def _target_key(self):
        return '|'.join(str(x or '') for x in (self.repository_id.id, self.operation, self.ref, self.file_path, self.number))

    @api.onchange('repository_id', 'operation', 'ref', 'file_path', 'number')
    def _clear_loaded(self):
        self.loaded_sha = False
        self.loaded_target = False

    @api.onchange('repository_id')
    def _default_branch(self):
        if self.repository_id:
            self.ref = self.repository_id.default_branch or 'main'
            self.base = self.ref

    def _check(self):
        self.ensure_one()
        require_group(self.env, 'group_admin')
        self.check_access_rights('write')
        self.check_access_rule('write')
        if self.attempt_id:
            raise UserError(_('This action has already been submitted. Check Action History before creating another.'))
        if self.operation != 'repo_create' and not self.repository_id:
            raise UserError(_('Select a repository.'))
        if self.repository_id:
            self.repository_id.check_access_rights('read')
            self.repository_id.check_access_rule('read')

    def _file_endpoint(self):
        path = self.file_path or ''
        if not path or path.startswith('/') or any(part in ('', '.', '..') for part in path.split('/')) or any(ord(c) < 32 for c in path):
            raise UserError(_('Enter a relative repository file path, such as addons/my_module/models/model.py.'))
        return self.repository_id._path() + '/contents/' + quote(path, safe='/')

    def action_load(self):
        self._check()
        if self.operation in ('file_update', 'file_delete'):
            data = github(self.env, self._file_endpoint() + '?ref=' + quote(self.ref or '', safe=''))
            if not isinstance(data, dict) or data.get('type') != 'file' or data.get('encoding') != 'base64' or data.get('size', 0) > 500000:
                raise UserError(_('This editor supports UTF-8 text files up to 500 KB.'))
            try:
                self.content = base64.b64decode(data['content']).decode('utf-8')
            except (ValueError, UnicodeError):
                raise UserError(_('This file is not UTF-8 text.')) from None
            self.loaded_sha = data['sha']
        elif self.operation.startswith('pr_') and self.operation != 'pr_create':
            if self.number < 1:
                raise UserError(_('Enter a pull request number.'))
            data = github(self.env, self.repository_id._path() + '/pulls/%s' % self.number)
            self.title = data['title']
            self.body = False if self.operation == 'pr_review' else data.get('body')
            self.loaded_sha = data['head']['sha']
        elif self.operation == 'issue_edit':
            if self.number < 1:
                raise UserError(_('Enter an issue number.'))
            data = github(self.env, self.repository_id._path() + '/issues/%s' % self.number)
            self.title, self.body = data['title'], data.get('body')
        else:
            raise UserError(_('Load Details is available for editing files, issues, or existing pull requests.'))
        self.loaded_target = self._target_key()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    def _request_values(self):
        op = self.operation
        path = self.repository_id._path() if self.repository_id else ''
        if op == 'repo_create':
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.repo_name or '') or self.repo_name in ('.', '..'):
                raise UserError(_('Enter a valid new repository name.'))
            if self.organization and not re.fullmatch(r'[A-Za-z0-9_-]+', self.organization):
                raise UserError(_('Enter an organization name, not a URL.'))
            endpoint = '/orgs/' + quote(self.organization, safe='') + '/repos' if self.organization else '/user/repos'
            return 'POST', endpoint, {'name': self.repo_name, 'description': self.body or '', 'private': self.private, 'auto_init': True}
        if op == 'repo_describe':
            return 'PATCH', path, {'description': self.body or ''}
        if op in ('repo_archive', 'repo_unarchive'):
            return 'PATCH', path, {'archived': op == 'repo_archive'}
        if op == 'repo_delete':
            if self.confirmation != self.repository_id.name:
                raise UserError(_('Type the full owner/repository name to confirm deletion.'))
            return 'DELETE', path, None
        if op.startswith('branch_'):
            if not self.ref:
                raise UserError(_('Enter the branch name.'))
            if op in ('branch_create', 'branch_rename') and not self.new_branch:
                raise UserError(_('Enter the new branch name.'))
            if op == 'branch_create':
                commit = github(self.env, path + '/branches/' + quote(self.ref, safe=''))['commit']['sha']
                return 'POST', path + '/git/refs', {'ref': 'refs/heads/' + self.new_branch, 'sha': commit}
            if op == 'branch_rename':
                return 'POST', path + '/branches/' + quote(self.ref, safe='') + '/rename', {'new_name': self.new_branch}
            if self.ref == self.repository_id.default_branch:
                raise UserError(_('The default branch cannot be deleted here.'))
            if self.confirmation != self.ref:
                raise UserError(_('Type the branch name to confirm deletion.'))
            return 'DELETE', path + '/git/refs/heads/' + quote(self.ref, safe=''), None
        if op.startswith('file_'):
            endpoint = self._file_endpoint()
            if not self.ref or not self.commit_message:
                raise UserError(_('Enter the branch and commit message.'))
            payload = {'branch': self.ref, 'message': self.commit_message}
            if op != 'file_create':
                if not self.loaded_sha or self.loaded_target != self._target_key():
                    raise UserError(_('Load and review this file before changing or deleting it.'))
                payload['sha'] = self.loaded_sha
            if op != 'file_delete':
                encoded = (self.content or '').encode('utf-8')
                if len(encoded) > 500000:
                    raise UserError(_('Use a local Git client for files larger than 500 KB.'))
                payload['content'] = base64.b64encode(encoded).decode()
            return 'DELETE' if op == 'file_delete' else 'PUT', endpoint, payload
        if op in ('pr_create', 'issue_create', 'pr_edit', 'issue_edit') and not self.title:
            raise UserError(_('Enter a title.'))
        if op == 'pr_create':
            if not self.head or not self.base:
                raise UserError(_('Enter source and target branches.'))
            return 'POST', path + '/pulls', {'title': self.title, 'body': self.body or '', 'head': self.head, 'base': self.base, 'draft': self.draft}
        if op == 'issue_create':
            return 'POST', path + '/issues', {'title': self.title, 'body': self.body or ''}
        if self.number < 1:
            raise UserError(_('Enter an issue or pull request number.'))
        endpoint = path + ('/pulls/' if op.startswith('pr_') else '/issues/') + str(self.number)
        if op in ('pr_edit', 'issue_edit'):
            return 'PATCH', endpoint, {'title': self.title, 'body': self.body or ''}
        if op in ('pr_close', 'issue_close', 'pr_reopen', 'issue_reopen'):
            return 'PATCH', endpoint, {'state': 'closed' if op.endswith('close') else 'open'}
        if op == 'pr_merge':
            if not self.loaded_sha or self.loaded_target != self._target_key():
                raise UserError(_('Load and review the pull request before merging.'))
            return 'PUT', endpoint + '/merge', {'merge_method': self.merge_method, 'sha': self.loaded_sha}
        if op == 'pr_review':
            if not self.loaded_sha or self.loaded_target != self._target_key():
                raise UserError(_('Load the pull request before reviewing it.'))
            if self.review_event in ('COMMENT', 'REQUEST_CHANGES') and not self.body:
                raise UserError(_('Enter your review comment.'))
            return 'POST', endpoint + '/reviews', {'event': self.review_event, 'body': self.body or '', 'commit_id': self.loaded_sha}
        if op == 'comment':
            if not self.body:
                raise UserError(_('Enter a comment.'))
            return 'POST', path + '/issues/%s/comments' % self.number, {'body': self.body}
        raise UserError(_('Unsupported action.'))

    def action_apply(self):
        self._check()
        # Serialize repeated clicks, and persist an attempt before any remote mutation.
        self.env.cr.execute('SELECT id FROM sh_github_action WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['attempt_id'])
        self._check()
        method, path, payload = self._request_values()
        log = self.env['sh.github.action.log'].sudo().create({
            'operation': self.operation, 'repository_name': self.repository_id.name or self.repo_name,
            'requested_by': self.env.uid, 'target': self.file_path or str(self.number or '') or self.new_branch or self.ref,
            'state': 'submitting', 'message': 'Request may be in progress. Check GitHub before submitting again.'})
        self.attempt_id = log
        self.env.cr.commit()
        try:
            response = github(self.env, path, method=method, payload=payload)
            if self.operation == 'pr_merge' and not response.get('merged'):
                raise UserError('GitHub did not merge the pull request. Check conflicts and branch protection.')
            log.write({'state': 'success', 'message': 'GitHub confirmed this action. Refresh repository data to see the changes.'})
            if self.operation == 'repo_delete':
                self.repository_id.sudo().active = False
            if self.operation == 'repo_create':
                self.env['sh.github.repository'].sudo().create({'name': response['full_name'],
                    'owner': response['owner']['login'], 'repository': response['name'],
                    'default_branch': response.get('default_branch'), 'private': response.get('private', True)})
        except UserError as exc:
            log.write({'state': 'attention', 'message': str(exc)})
        self.env.cr.commit()
        return {'type': 'ir.actions.act_window', 'name': 'GitHub Action Result',
                'res_model': 'sh.github.action.log', 'res_id': log.id, 'view_mode': 'form', 'target': 'current'}
