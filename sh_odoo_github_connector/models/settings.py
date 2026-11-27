from odoo import fields, models, _
from odoo.exceptions import AccessError
from .connector import github, notice


class Settings(models.TransientModel):
    _inherit = 'res.config.settings'

    sh_github_token = fields.Char(string='GitHub Personal Access Token',
        config_parameter='sh_github.token', groups='base.group_system')
    def _check_github_settings(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings administrators can manage credentials.'))

    def action_sh_test_token(self):
        self.ensure_one()
        self._check_github_settings()
        user = github(self.env, '/user', token=self.sh_github_token)
        return notice(_('Connected as %s') % user.get('login', 'GitHub user'))

    def action_sh_sync_repositories(self):
        self.ensure_one()
        self._check_github_settings()
        count = self.env['sh.github.repository']._sync(self.sh_github_token)
        return notice(_('%s repositories synchronized. Save Settings before running jobs.') % count)

    def action_sh_connect(self):
        self.ensure_one()
        self._check_github_settings()
        user = github(self.env, '/user', token=self.sh_github_token)
        count = self.env['sh.github.repository']._sync(self.sh_github_token)
        self.env['ir.config_parameter'].sudo().set_param('sh_github.token', self.sh_github_token)
        return notice(_('Connected as %s. Token saved; %s repositories loaded. Open GitHub → Repositories to continue.') % (user.get('login', 'GitHub user'), count))

