import re
from urllib.parse import quote

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

PREFIX = 'sh_odoo_github_connector.'


def require_group(env, group):
    if not env.user.has_group(PREFIX + group):
        raise AccessError(_('You do not have permission for this operation.'))


def notice(message):
    return {'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': 'GitHub Connector', 'message': message, 'type': 'success'}}


def github(env, path, token=None, method='GET', payload=None):
    if token is None:
        token = env['ir.config_parameter'].sudo().get_param('sh_github.token')
    if not token:
        raise UserError('Open Settings → GitHub Connector, paste your token, and click Connect & Sync.')
    try:
        response = requests.request(method, 'https://api.github.com' + path,
            headers={'Authorization': 'Bearer ' + token,
                     'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2026-03-10'},
            json=payload, timeout=(5, 25), allow_redirects=False)
        status = response.status_code
        if status not in (200, 201, 202, 204):
            if status == 401:
                message = 'Your GitHub token is invalid or expired. Replace it in Settings → GitHub Connector.'
            elif status in (403, 429):
                if response.headers.get('X-RateLimit-Remaining') == '0' or response.headers.get('Retry-After'):
                    message = 'GitHub rate limit reached. Wait before trying again; repeated clicks will not help.'
                elif response.headers.get('X-GitHub-SSO'):
                    message = 'Your organization requires SSO authorization for this token. Authorize it in GitHub token settings.'
                else:
                    permissions = response.headers.get('X-Accepted-GitHub-Permissions', '')
                    permissions = permissions if re.fullmatch(r'[a-zA-Z0-9_=,; -]{0,250}', permissions) else ''
                    message = ('GitHub denied this action (403). In GitHub → Settings → Developer settings → '
                               'Personal access tokens, edit this token and select this repository. '
                               'For branch access/tests enable Repository permissions → Contents → Read. '
                               'To change files or branches use Contents → Read and write; for issues/PRs enable their respective write permissions. '
                               'Save the token changes and obtain organization approval if required.')
                    if permissions:
                        message += ' GitHub requires: ' + permissions + '.'
            elif status == 404:
                message = 'GitHub could not find this repository, branch, or item. Check its name and the repositories selected for your token.'
            elif status in (409, 422, 405):
                message = ('GitHub rejected the change (HTTP %s). Check for an empty repository, duplicate branch, '
                           'stale file/head SHA, merge conflicts, or branch protection rules. Reload details before retrying.') % status
            else:
                message = 'GitHub returned HTTP %s. Check GitHub availability and token access.' % status
            raise UserError(message)
        return {} if status == 204 else response.json()
    except (requests.RequestException, ValueError):
        message = 'GitHub could not be reached or returned an invalid response.'
        if method != 'GET':
            message += ' The change may already have been applied. Check GitHub before submitting a new action.'
        raise UserError(message) from None


def pages(env, path, token=None):
    # Construct pagination locally; never forward credentials to a Link header URL.
    for page in range(1, 101):
        rows = github(env, path + ('&' if '?' in path else '?') + 'per_page=100&page=%s' % page, token)
        if not isinstance(rows, list):
            raise UserError('Unexpected GitHub response.')
        yield from rows
        if len(rows) < 100:
            return
    raise UserError('More than 10,000 entries; narrow the token repository access.')


class Repository(models.Model):
    _name = 'sh.github.repository'
    _description = 'GitHub Repository'
    _order = 'name'

    name = fields.Char(required=True, readonly=True)
    owner = fields.Char(required=True, readonly=True)
    repository = fields.Char(required=True, readonly=True)
    default_branch = fields.Char(readonly=True)
    active = fields.Boolean(default=True)
    private = fields.Boolean(readonly=True)

    @api.model
    def _sync(self, token=None):
        rows = list(pages(self.env, '/user/repos?sort=full_name', token))
        Repo = self.sudo().with_context(active_test=False)
        seen = []
        for row in rows:
            values = {'name': row['full_name'], 'owner': row['owner']['login'],
                      'repository': row['name'], 'default_branch': row.get('default_branch'),
                      'private': row.get('private', False), 'active': True}
            record = Repo.search([('name', '=', row['full_name'])], limit=1)
            if record:
                record.write(values)
            else:
                record = Repo.create(values)
            seen.append(record.id)
        Repo.search([('id', 'not in', seen)]).write({'active': False})
        return len(seen)


class Branch(models.Model):
    _name = 'sh.github.branch'
    _description = 'GitHub Branch'
    _order = 'name'

    name = fields.Char(required=True, readonly=True)
    repository_id = fields.Many2one('sh.github.repository', required=True, ondelete='cascade', readonly=True)
    commit_sha = fields.Char(readonly=True)
    active = fields.Boolean(default=True)


class Project(models.Model):
    _name = 'sh.github.project'
    _description = 'Archived CI/CD Project'
    name = fields.Char()
    active = fields.Boolean(default=False)
    owner = fields.Char()
    repository = fields.Char()
    branch = fields.Char()
    environment = fields.Char()
    run_ids = fields.One2many('sh.github.run', 'project_id', readonly=True)


class Run(models.Model):
    _name = 'sh.github.run'
    _description = 'Archived Pipeline Run'
    _rec_name = 'request_id'
    _order = 'id desc'
    project_id = fields.Many2one('sh.github.project', ondelete='restrict')
    request_id = fields.Char(readonly=True)
    requested_by = fields.Many2one('res.users', readonly=True)
    operation = fields.Char(readonly=True)
    environment = fields.Char(readonly=True)
    owner = fields.Char(readonly=True)
    repository = fields.Char(readonly=True)
    branch = fields.Char(readonly=True)
    state = fields.Char(readonly=True)
    conclusion = fields.Char(readonly=True)
    commit_sha = fields.Char(readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    last_checked = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)
    log = fields.Text(readonly=True)

    @api.model
    def _cron_process(self):
        # Compatibility only: an old noupdate cron must never execute jobs.
        return None
