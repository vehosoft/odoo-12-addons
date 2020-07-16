# Copyright VeHoSoft - Vertical & Horizontal Software (http://www.vehosoft.com)
# Code by: Francisco Rodriguez (frodriguez@vehosoft.com).

from odoo import api, fields, models

class SATProductClave(models.Model):
    _name = 'sat.product.clave'
    _description = 'Clave SAT de Productos'

    @api.multi
    def name_get(self):
        resp = []
        for uso in self:
            name = str(uso.code) + ' - ' + str(uso.name)
            resp.append((uso.id, name))
        return resp

    code = fields.Char(string='Clave', size=12, index=True,required=True)
    name = fields.Char(string='Descripcion', size=120, index=True,required=True)

class ProductTemplate(models.Model):
    _inherit = "product.template"

    clave_sat = fields.Many2one('sat.product.clave', string="Clave SAT", help='Clave SAT para el CFDI')
    number_ident = fields.Char(string='Numero de Identificacion', size=30)

class UomUom(models.Model):
    _inherit = "uom.uom"

    clave_sat = fields.Char(string='Clave SAT', size=12)
