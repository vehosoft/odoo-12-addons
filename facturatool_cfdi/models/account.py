# Copyright VeHoSoft - Vertical & Horizontal Software (http://www.vehosoft.com)
# Code by: Francisco Rodriguez (frodriguez@vehosoft.com).

from odoo import api, fields, exceptions, models, _
from odoo.exceptions import AccessError, UserError, RedirectWarning, ValidationError, Warning
from lxml import etree
import json
import qrcode
import base64
import tempfile
import logging
_logger = logging.getLogger(__name__)

try:
	import zeep
except ImportError:  # pragma: no cover
	_logger.debug('Cannot import zeep')

class AccountTax(models.Model):
	_inherit = 'account.tax'

	clave_sat = fields.Char(string='Clave SAT', size=3)
	type_tax_sat = fields.Selection([('traslado', 'Trasladado'), ('retencion', 'Retencion')], string='Tipo de Impuesto',help="Determina el tipo de Impuesto en el CFDI")
	tipo_factor_sat = fields.Selection([('Tasa', 'Tasa'), ('Cuota', 'Cuota'), ('Excento', 'Excento')], string='Tipo o Factor',help="Determina el tipo de Factor en el CFDI")

class AccountInvoiceLine(models.Model):
	_inherit = 'account.invoice.line'

	clave_sat = fields.Many2one('sat.product.clave', string="Clave SAT", help='Clave SAT para el CFDI')
	number_ident = fields.Char(string='Numero de Identificacion', size=30)

	@api.onchange('product_id')
	def _onchange_product_id(self):
		res = super(AccountInvoiceLine, self)._onchange_product_id()
		if not self.invoice_id:
			return

		part = self.invoice_id.partner_id
		type = self.invoice_id.type

		if not part:
			return res

		if type=='out_invoice' and self.product_id:
			self_lang = self
			if part.lang:
				self_lang = self.with_context(lang=part.lang)

			product = self_lang.product_id

			self.clave_sat = product.clave_sat
			self.number_ident = product.number_ident
		return res

class AccountInvoice(models.Model):
	_inherit = 'account.invoice'

	cfdi_trans_id = fields.Char(string='FacturaTool TransID', size=30, copy=False)
	cfdi_uso = fields.Many2one('sat.cfdi.uso', string="Uso del CFDI")
	cfdi_state = fields.Selection([('draft', 'Sin Timbrar'), ('done', 'Trimbrado'), ('cancel', 'Cancelado')], string='Status del CFDI', default='draft', copy=False, track_visibility='onchange')
	cfdi_hora = fields.Float('Hora factura')
	cfdi_hora_str = fields.Char('Hora factura Texto',compute='_cfdi_hora_str')
	cfdi_serie = fields.Many2one('facturatool.serie', string="Serie")
	cfdi_folio = fields.Char(string='Folio', size=30, copy=False, track_visibility='onchange')
	cfdi_uuid = fields.Char(string='UUID', size=120, copy=False, track_visibility='onchange')
	cfdi_metodo_pago = fields.Selection([('PUE', 'Pago en una sola exhibicion'), ('PPD', 'Pago en parcialidades o diferido')], string='Metodo de Pago', default='PUE')
	cfdi_forma_pago = fields.Many2one('sat.forma.pago', string="Forma de Pago")
	cfdi_fecha_timbrado = fields.Datetime(string='Fecha de timbrado', copy=False, track_visibility='onchange')
	cfdi_xml = fields.Text('XML', copy=False)
	cfdi_acuse_emision = fields.Text('Acuse de Emision', copy=False)
	cfdi_serie_csd = fields.Char(string='Serie CSD', size=600, copy=False)
	cfdi_serie_sat = fields.Char(string='Serie SAT', size=600, copy=False)
	cfdi_sello_digital = fields.Char(string='Sello Digital', size=600, copy=False)
	cfdi_sello_sat = fields.Char(string='Sello SAT', size=600, copy=False)
	cfdi_cadena_original = fields.Char(string='Cadena Original', size=600, copy=False)
	cfdi_codigo_qr = fields.Binary('Codigo QR', copy=False)

	def _cfdi_hora_str(self):
		for record in self:
			float_time = str(record.cfdi_hora)
			float_time = float_time.split('.')
			hours =  float_time[0]
			mins = int(float_time[1])
			mins =int( (mins * 60) / 10 )
			mins = str(mins)
			if len(hours) == 1:
				hours = '0' + hours
			if len(mins) > 1:
				mins = mins[0:2]
			else:
				mins = mins + '0'
			record.cfdi_hora_str = hours +':'+ mins

	@api.onchange('partner_id', 'company_id')
	def _onchange_partner_id(self):
		res = super(AccountInvoice, self)._onchange_partner_id()
		type = self.type or self.env.context.get('type', 'out_invoice')
		if type == 'out_invoice':
			self.cfdi_uso = self.partner_id.cfdi_uso
		return res

	@api.onchange('cfdi_metodo_pago')
	def _onchange_cfdi_metodo_pago(self):
		res = {}
		type = self.type or self.env.context.get('type', 'out_invoice')
		if type == 'out_invoice' and self.cfdi_metodo_pago == 'PPD':
			fp_pd = self.env['sat.forma.pago'].search([('code','=','99')], limit=1)
			self.cfdi_forma_pago = fp_pd
		return res

	@api.multi
	def action_timbrar_cfdi(self):
		status = False
		invoices = self.filtered(lambda inv: inv.cfdi_state == 'draft')
		ft_account = self.env['facturatool.account'].search([('rfc','!=','')], limit=1)
		if ft_account.rfc == False:
			msg = 'Error #8001: Necesita configurar su cuenta FacturaTool en "Contabilidad/Configuracion/Facturacion Electronica/Cuenta FacturaTool"'
			raise UserError(msg)

		wsdl = 'http://ws.facturatool.com/index.php?wsdl'
		client = zeep.Client(wsdl)

		for invoice in invoices:
			if invoice.partner_id.is_company == True:
				razon_social = invoice.partner_id.razon_social
			else:
				razon_social = invoice.partner_id.name

			receptor = {
				'Rfc': invoice.partner_id.vat,
				'Nombre': razon_social,
				'UsoCFDI': invoice.cfdi_uso.code,
			}

			conceptos = []
			taxes = []
			iline = 0
			itax = 0
			discount=0
			for line in invoice.invoice_line_ids:
				tax_include_on_price = False
				for tax in line.invoice_line_tax_ids:
					tax_factor = 1.00
					if tax.amount < 0.00:
						tax_factor = -1.00
					if tax.amount_type=='percent' and tax.type_tax_sat != False:
						tax_obj = {
							'Nombre': tax.name,
							'Tipo': tax.type_tax_sat,
							'Impuesto': tax.clave_sat,
							'Base': line.price_subtotal,
							'TipoFactor': tax.tipo_factor_sat,
							'TasaOCuota': (float(tax.amount)/100.00) * tax_factor,
							'Importe': float(line.price_subtotal) * (float(tax.amount)/100.00) * tax_factor,
							'indexConcepto': iline
						}
						taxes[itax:itax]=[tax_obj]
					itax = itax + 1
					if tax.price_include:
						tax_include_on_price = True
				ValorUnitario = line.price_unit
				if tax_include_on_price:
					ValorUnitario = float(line.price_subtotal) / float(line.quantity)
				concepto = {
					'ClaveProdServ': line.clave_sat.code,
					'Cantidad': line.quantity,
					'Descripcion': line.name,
					'ClaveUnidad': line.uom_id.clave_sat,
					'Unidad': line.uom_id.name,
					'ValorUnitario': ValorUnitario,
					'Importe': line.price_subtotal,
					#'Redondeo': 'weikov',
					'indexConcepto': iline
				}
				if line.number_ident != '' and line.number_ident != False:
					concepto['NoIdentificacion'] = line.number_ident
				if line.discount > 0:
					discount = discount + line.discount
					concepto['Descuento'] = line.discount

				conceptos[iline:iline]=[concepto]
				iline = iline + 1

			params = {
				'Rfc': ft_account.rfc,
				'Usuario': ft_account.username,
				'Password': ft_account.password,
				'Serie': invoice.cfdi_serie.name,
				'Fecha': invoice.date_invoice,
				'Hora': invoice.cfdi_hora_str,
				'FormaPago': invoice.cfdi_forma_pago.code,
				'MetodoPago': invoice.cfdi_metodo_pago,
				#'TipoDeComprobante': 'I',
				'Moneda': 'MXN',#factura.currency_id.name, hasta que se implemente timbrado para monedas distintas a MXN
				'LugarExpedicion': invoice.company_id.zip,
				'Receptor': receptor,
				'Conceptos': conceptos,
				'SubTotal': invoice.amount_untaxed,
				'Total': invoice.amount_total,
				'IdExterno': invoice.number,
				#'Redondeo': 'imp',
			}
			if len(taxes) > 0:
				params['Impuestos'] =  taxes
			if invoice.payment_term_id:
				params['CondicionesDePago'] = invoice.payment_term_id.name
			#if invoice.partner_id.email:
			#    params['EnviarEMail'] = 1
			#    params['EMail'] = invoice.partner_id.email

			_logger.debug('===== action_timbrar_cfdi params = %r',params)
			result = client.service.crearCFDI(params=params)
			_logger.debug('===== action_timbrar_cfdi result = %r',result)
			ws_res = json.loads(result)
			_logger.debug('===== action_timbrar_cfdi ws_res = %r',ws_res)

			if ws_res['success'] == True:
				status = True

				cfdi = etree.fromstring(ws_res['xml'].encode('utf-8'))
				ns = {'c':'http://www.sat.gob.mx/cfd/3','d':'http://www.sat.gob.mx/TimbreFiscalDigital'}
				nodoT=cfdi.xpath('c:Complemento ', namespaces=ns)
				sello_digital = cfdi.get("Sello")
				serie_csd = cfdi.get("NoCertificado")

				for nodo in nodoT:
					nodoAux=nodo.xpath('d:TimbreFiscalDigital', namespaces=ns)
					uuid=nodoAux[0].get("UUID")
					serie_sat = nodoAux[0].get("NoCertificadoSAT")
					sello_sat = nodoAux[0].get("SelloSAT")
				cadena_orginal = '||1.0|'+ws_res['uuid']+'|'+ws_res['fecha_timbrado']+'|'+invoice.cfdi_serie.name+str(ws_res['folio'])+'|'+sello_digital+'|'+serie_sat+'||'

				qr = qrcode.QRCode(
					version=1,
					error_correction=qrcode.constants.ERROR_CORRECT_L,
					box_size=4,
					border=1,
				)
				qr.add_data("{'emisor':'"+ft_account.rfc+"','receptor':'"+receptor['Rfc']+"','total':'"+str(ws_res['total'])+"','uuid':'"+ws_res['uuid']+"','serie':'"+ws_res['serie']+"','folio':'"+str(ws_res['folio'])+"'}")
				qr.make(fit=True)
				imgQR = qr.make_image()
				fname=tempfile.NamedTemporaryFile(suffix='.png',delete=False)
				_logger.debug('===== action_timbrar_cfdi fname = %r',fname.name)
				imgQR.save(fname.name)
				f = open(fname.name, "r",encoding="latin-1")
				dataQR = f.read()
				f.close()
				_logger.debug('===== action_timbrar_cfdi dataQR = %r',dataQR)
				invoice.write({
					'cfdi_state':'done',
					'cfdi_trans_id':ws_res['trans_id'],
					'cfdi_folio':ws_res['folio'],
					'cfdi_uuid':ws_res['uuid'],
					'cfdi_fecha_timbrado':ws_res['fecha_timbrado'],
					'cfdi_xml':ws_res['xml'],
					'cfdi_sello_sat':sello_sat,
					'cfdi_serie_sat':serie_sat,
					'cfdi_sello_digital':sello_digital,
					'cfdi_serie_csd':serie_csd,
					'cfdi_cadena_original':str(cadena_orginal),
					'cfdi_codigo_qr':base64.b64encode(dataQR.encode()),
					#'cfdi_codigo_qr':dataQR,
				})

				filename=ft_account.rfc+'_'
				filename+=invoice.cfdi_serie.name.strip().upper()
				filename+=ws_res['folio'].strip()

				try:
					self.env['ir.attachment'].create({
						'name': filename + ".xml",
						'type': 'binary',
						'res_id': invoice.id,
						'res_model': 'account.invoice',
						'datas': base64.b64encode(ws_res['xml'].encode()),
						'mimetype': 'application/xml',
						'datas_fname': filename + ".xml"
					})
				except:
					pass

			else:
				if ws_res['error'] is None:
					error = "Servicio temporalmente fuera de servicio"
				else:
					error = ws_res['error']
				msg = 'Error #' + str(ws_res['errno']) + ': ' + error
				raise UserError(msg)

		return {'params': params,'status': status}
