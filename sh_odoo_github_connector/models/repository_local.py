import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .connector import require_group
from .local_git import GitError, run_repository


class Repository(models.Model):
    _inherit = 'sh.github.repository'

    clone_path = fields.Char(string='Clone Path', help='Full destination directory on the Odoo machine, including the repository folder.')
    clone_branch = fields.Char(string='Clone Branch', help='Leave empty to use the GitHub default branch.')
    local_commit = fields.Char(readonly=True)
    local_updated_at = fields.Datetime(readonly=True)
    local_log = fields.Text(readonly=True)

    @api.constrains('clone_path')
    def _check_clone_path(self):
        from pathlib import Path
        for repo in self:
            if repo.clone_path and (not Path(repo.clone_path).expanduser().is_absolute() or any(ord(c) < 32 for c in repo.clone_path)):
                raise ValidationError(_('Clone Path must be an absolute directory path.'))

    def action_clone(self):
        return self._local_operation('clone')

    def action_pull(self):
        return self._local_operation('pull')

    def _local_operation(self, operation):
        self.ensure_one()
        require_group(self.env, 'group_admin')
        self.check_access_rights('write')
        self.check_access_rule('write')
        if not self.clone_path:
            raise UserError(_('Enter and save Clone Path on this repository first.'))
        if not all(re.fullmatch(r'[A-Za-z0-9_.-]+', x or '') and x not in ('.', '..') for x in (self.owner, self.repository)):
            raise UserError(_('Sync this repository again; owner or repository name is invalid.'))
        token = self.env['ir.config_parameter'].sudo().get_param('sh_github.token')
        if not token:
            raise UserError(_('Save your GitHub token in Settings first.'))
        branch = self.clone_branch or self.default_branch
        if not branch:
            raise UserError(_('Set Clone Branch, or refresh the repository to load its default branch.'))
        # Persist the user's selected path before touching the filesystem. Remote/FS changes cannot be rolled back by PostgreSQL.
        self.env.cr.commit()
        try:
            sha, message = run_repository(operation, self.clone_path, self.owner + '/' + self.repository, branch, token)
            self.sudo().write({'local_commit': sha, 'local_updated_at': fields.Datetime.now(), 'local_log': message})
            title, kind = _('Repository ready'), 'success'
        except (GitError, OSError) as exc:
            message = str(exc) if isinstance(exc, GitError) else 'Odoo could not access Git or the selected path. Check OS-user permissions and that /usr/bin/git is installed.'
            self.sudo().local_log = message
            title, kind = _('Clone / Pull did not complete'), 'warning'
        self.env.cr.commit()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': title, 'message': message, 'type': kind, 'sticky': True,
            'next': {'type': 'ir.actions.client', 'tag': 'reload'}}}
