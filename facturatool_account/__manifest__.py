# Copyright VeHoSoft - Vertical & Horizontal Software
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    'name': 'Cuenta FacturaTool',
    'summary': 'Administracion de cuenta FacturaTool',
    'version': '12.0.1.0.5',
    'category': 'Invoicing Management',
    'author': 'VeHoSoft',
    'website': 'http://www.vehosoft.com',
    'license': 'AGPL-3',
    'depends': [
        'account','web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/data_catalogos_sat.xml',
        'views/layout_views.xml',
        'views/facturatool_menuitems.xml',
        'views/facturatool_views.xml',
    ],
    'qweb': [

    ],
    'application': False,
    'installable': True,
    "external_dependencies": {
        "python": ["SOAPpy"],
    },
}
