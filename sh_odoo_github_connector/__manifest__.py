{'name': 'SH Odoo GitHub Connector',
 'version': '17.0.5.2.0',
 'summary': 'Manage GitHub repositories, branches, pull requests and issues; clone and pull '
            'locally',
 'description': 'SH Odoo GitHub Connector\n'
                '========================\n'
                'Manage GitHub repositories from Odoo with a personal access token.\n'
                '\n'
                'Features\n'
                '--------\n'
                '* Synchronize repositories and browse branches, commits, pull requests and '
                'issues.\n'
                '* Configure a separate clone path and branch for every repository.\n'
                '* Clone and fast-forward pull source code directly on the Odoo server.\n'
                '* Create, rename and delete branches; create, edit and commit text files.\n'
                '* Create, edit, review and merge pull requests; manage issues and comments.\n'
                '* Manage repository descriptions, creation, archiving and deletion.\n'
                '* Review action history with Viewer, Operator and Administrator access levels.\n'
                '* Use repository cards, filters, status badges and a code editor.\n'
                '\n'
                'Requirements and scope\n'
                '----------------------\n'
                'Requires Git, the Python requests package, a GitHub personal access token\n'
                'with suitable repository permissions, and writable local clone directories.\n'
                'No YAML workflow or separate deployment worker is required.\n'
                'Clone and pull update source files only. Odoo module installation, upgrades\n'
                'and service restarts are performed separately.\n'
                'Tokens are stored in the Odoo database; masking does not encrypt them.\n'
                '\n'
                'Developer and contact\n'
                '---------------------\n'
                'Muhammad Shuhaife (Shuhaife Binhamza) - Odoo Developer\n'
                'Portfolio: https://shuhaife.pages.dev/\n'
                'GitHub: https://github.com/muhammad-shuhaife\n'
                'LinkedIn: https://www.linkedin.com/in/shuhaife-binhamza/\n'
                'Support: shuhaifebinhamza@gmail.com\n',
 'author': 'Shuhaife Binhamza',
 'maintainer': 'Shuhaife Binhamza',
 'website': 'https://shuhaife.pages.dev/',
 'support': 'shuhaifebinhamza@gmail.com',
 'category': 'Administration',
 'license': 'LGPL-3',
 'depends': ['base_setup'],
 'external_dependencies': {'python': ['requests']},
 'data': ['security/security.xml',
          'security/ir.model.access.csv',
          'views/connector_views.xml',
          'views/settings_views.xml',
          'views/management_views.xml',
          'data/cron.xml'],
 'assets': {'web.assets_backend': ['sh_odoo_github_connector/static/src/scss/connector.scss']},
 'application': True,
 'installable': True,
 'auto_install': False,
 'images': ['static/description/banner.png']}
