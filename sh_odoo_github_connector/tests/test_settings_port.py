from unittest.mock import patch
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPortSettings(TransactionCase):
    def test_connect_saves_token(self):
        settings = self.env['res.config.settings'].create({'sh_github_token': 'fixture-token'})
        with patch('odoo.addons.sh_odoo_github_connector.models.settings.github', return_value={'login': 'fixture'}), patch.object(type(self.env['sh.github.repository']), '_sync', return_value=2):
            result = settings.action_sh_connect()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('sh_github.token'), 'fixture-token')
        self.assertEqual(result['params']['type'], 'success')
