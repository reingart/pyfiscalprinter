#!/usr/bin/python
# -*- coding: latin-1 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTIBILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.

"Interfaz de alto nivel para automatización de controladores fiscales"

__author__ = "Mariano Reingart <reingart@gmail.com>"
__copyright__ = "Copyright (C) 2014 Mariano Reingart"
__license__ = "GPL 3.0"
__version__ = "1.00a"

CONFIG_FILE = "fiscal.ini"
DEBUG = True

LICENCIA = u"""
Interfaz para imprimir Facturas y Tickets en Controladores Fiscales
Copyright (C) 2014 Mariano Reingart reingart@gmail.com

Este progarma es software libre, se entrega ABSOLUTAMENTE SIN GARANTIA
y es bienvenido a redistribuirlo bajo la licencia GPLv3.

Para información adicional sobre garantía, soporte técnico comercial
e incorporación/distribución en programas propietarios ver PyAfipWs:
http://www.sistemasagiles.com.ar/trac/wiki/PyFiscalPrinter
"""

AYUDA=u"""
Opciones: 
  --ayuda: este mensaje
  --licencia: muestra la licencia del programa

  --debug: modo depuración (detalla y confirma las operaciones)
  --formato: muestra el formato de los archivos de entrada/salida
  --ult: consulta y devuelve el último número de comprobante impreso
  --prueba: genera y autoriza una factura de prueba (no usar en producción!)
  --cargar: carga un archivo de entrada y lo procesa
  --grabar: graba un archivo de salida con los datos de los comprobantes procesados
  --dbf: utiliza tablas DBF en lugar del archivo de entrada TXT

Ver rece.ini para parámetros de configuración "
"""

import datetime
import decimal
import os
import sys
import traceback
from cStringIO import StringIO
from decimal import Decimal

# Drivers:

from epsonFiscal import EpsonPrinter
from hasarPrinter import HasarPrinter


def inicializar_y_capturar_excepciones(func):
    "Decorador para inicializar y capturar errores"
    def capturar_errores_wrapper(self, *args, **kwargs):
        try:
            # inicializo (limpio variables)
            self.Traceback = self.Excepcion = ""
            return func(self, *args, **kwargs)
        except Exception, e:
            ex = traceback.format_exception( sys.exc_type, sys.exc_value, sys.exc_traceback)
            self.Traceback = ''.join(ex)
            self.Excepcion = traceback.format_exception_only( sys.exc_type, sys.exc_value)[0]
            if self.LanzarExcepciones:
                raise
        finally:
            pass
    return capturar_errores_wrapper


class PyFiscalPrinter:
    "Interfaz unificada para imprimir facturas en controladores fiscales"
    _public_methods_ = ['Conectar',
                        'AbrirComprobante', 'CerrarComprobante',
                        'ImptrimirItem', 'ImprimirPago', 
                        'ConsultarUltNro',
                        ]
    _public_attrs_ = ['Version', 'Excepcion', 'Traceback', 'LanzarExcepciones',
                    ]
        
    _reg_progid_ = "PyFiscalPrinter"
    _reg_clsid_ = "{4E214B11-424E-40F7-9869-680C9520125E}"

    
    def __init__(self):
        self.Version = __version__
        self.factura = None
        self.Exception = self.Traceback = ""
        self.LanzarExcepciones = False
        self.factura = {}
        self.printer = None
        self.log = StringIO()

    @inicializar_y_capturar_excepciones
    def Conectar(self, marca="epson", modelo="320", puerto="COM1", equipo=None):
        "Iniciar la comunicación con la instancia del controlador fiscal"
        if marca == 'epson':
            Printer = EpsonPrinter
        elif marca == 'hasar':
            Printer = HasarPrinter
        dummy = True
        # instanciar la impresora fiscal
        if not equipo:
            # conexión por puerto serie
            printer = Printer(deviceFile=puerto, model=modelo, dummy=dummy)
        else:
            # conexion por proxy TCP/IP
            printer = driver(model=modelo, host=equipo, port=int(puerto), dummy=dummy)
        self.printer = printer
        self.cbte_fiscal_map = {
                                1: 'FA', 2: 'NDA', 3: 'NCA', 
                                6: 'FB', 7: 'NDB', 8: 'NCB', 
                                11: 'FC', 12: 'NDC', 13: 'NDC',
                                81:	'FA', 82: 'FB', 83: 'T',      # tiques
                                }
        self.pos_fiscal_map = {
                                1:  printer.IVA_TYPE_RESPONSABLE_INSCRIPTO,
                                2:	printer.IVA_TYPE_RESPONSABLE_NO_INSCRIPTO,
                                3:	printer.IVA_TYPE_NO_RESPONSABLE,
                                4:	printer.IVA_TYPE_EXENTO,
                                5:	printer.IVA_TYPE_CONSUMIDOR_FINAL,
                                6:	printer.IVA_TYPE_RESPONSABLE_MONOTRIBUTO,
                                7:	printer.IVA_TYPE_NO_CATEGORIZADO,
                                12:	printer.IVA_TYPE_PEQUENIO_CONTRIBUYENTE_EVENTUAL,
                                13: printer.IVA_TYPE_MONOTRIBUTISTA_SOCIAL,
                                14:	printer.IVA_TYPE_PEQUENIO_CONTRIBUYENTE_EVENTUAL_SOCIAL,
                                }
        self.doc_fiscal_map = {
                                96: printer.DOC_TYPE_DNI,
                                80: printer.DOC_TYPE_CUIT,
                                89: printer.DOC_TYPE_LIBRETA_ENROLAMIENTO,
                                90: printer.DOC_TYPE_LIBRETA_CIVICA,
                                00: printer.DOC_TYPE_CEDULA,
                                94: printer.DOC_TYPE_PASAPORTE, 
                                99: printer.DOC_TYPE_SIN_CALIFICADOR,
                              }

    def DebugLog(self):
        "Devolver bitácora de depuración"
        msg = self.log.getvalue()
        return msg    

    @inicializar_y_capturar_excepciones
    def AbrirComprobante(self, 
                         tipo_cbte=83,                              # tique
                         tipo_responsable=5,                        # consumidor final
                         tipo_doc=99, nro_doc=0,                    # sin especificar
                         nombre_cliente="", domicilio_cliente="",
                         referencia=None,                           # comprobante original (ND/NC)
                         **kwargs
                         ):
        "Creo un objeto factura (internamente)"
        printer = self.printer
        # mapear el tipo de comprobante según RG1785/04:
        cbte_fiscal = self.cbte_fiscal_map[int(tipo_cbte)]
        letra_cbte = cbte_fiscal[-1] if len(cbte_fiscal) > 1 else None
        # mapear el tipo de cliente (posicion/categoria) según RG1785/04:
        pos_fiscal = self.pos_fiscal_map[int(tipo_responsable)]
        # mapear el numero de documento según RG1361
        doc_fiscal = self.doc_fiscal_map[int(tipo_doc)]
        # cancelar y volver a un estado conocido
        printer.cancelAnyDocument()
        # enviar los comandos de apertura de comprobante fiscal:
        if cbte_fiscal.startswith('T'):
            if letra_cbte:
                ret = printer.openTicket(letra_cbte)
            else:
                ret = printer.openTicket()
        elif cbte_fiscal.startswith("F"):
            ret = printer.openBillTicket(letra_cbte, nombre_cliente, domicilio_cliente, 
                                         nro_doc, doc_fiscal, pos_fiscal)
        elif cbte_fiscal.startswith("ND"):
            ret = printer.openDebitNoteTicket(letra_cbte, nombre_cliente, 
                                              domicilio_cliente, nro_doc, doc_fiscal, 
                                              pos_fiscal)
        elif cbte_fiscal.startswith("NC"):
            ret = printer.openBillCreditTicket(letra_cbte, nombre_cliente, 
                                               domicilio_cliente, nro_doc, doc_fiscal, 
                                               pos_fiscal, referencia)
        return ret

    @inicializar_y_capturar_excepciones
    def ImprimirItem(self, ds, qty, importe, alic_iva=21.):
        "Envia un item (descripcion, cantidad, etc.) a una factura"
        ##ds = unicode(ds, "latin1") # convierto a latin1
        # Nota: no se calcula neto, iva, etc (deben venir calculados!)
        discount = discountDescription =  None
        return self.printer.addItem(ds, float(qty), float(importe), float(alic_iva), 
                                    discount, discountDescription)

    @inicializar_y_capturar_excepciones
    def ImprimirPago(self, ds, importe):
        "Imprime una linea con la forma de pago y monto"
        return self.printer.addPayment(ds, float(importe))

    @inicializar_y_capturar_excepciones
    def CerrarComprobante(self):
        "Envia el comando para cerrar un comprobante Fiscal"
        return self.printer.closeDocument()

    @inicializar_y_capturar_excepciones
    def ConsultarUltNro(self, tipo_cbte):
        "Devuelve el último número de comprobante"
        # mapear el numero de documento según RG1361
        cbte_fiscal = self.cbte_fiscal_map[int(tipo_cbte)]
        letra_cbte = cbte_fiscal[-1] if len(cbte_fiscal) > 1 else None
        return self.printer.getLastNumber(letra_cbte)


if __name__ == '__main__':

    if "--register" in sys.argv or "--unregister" in sys.argv:
        import win32com.server.register
        win32com.server.register.UseCommandLine(PyFiscalPrinter)
    else:
        from ConfigParser import SafeConfigParser

        DEBUG = '--debug' in sys.argv
                
        # leeo configuración (primer argumento o rece.ini por defecto)
        if len(sys.argv)>1 and not sys.argv[1].startswith("--"):
            CONFIG_FILE = sys.argv.pop(1)
        if DEBUG: print "CONFIG_FILE:", CONFIG_FILE
        
        config = SafeConfigParser()
        config.read(CONFIG_FILE)
        if config.has_section('CONTROLADOR'):
            conf = dict(config.items('CONTROLADOR'))
        else:
            conf = {}

        if '--ayuda' in sys.argv:
            print AYUDA
            sys.exit(0)

        if '--licencia' in sys.argv:
            print LICENCIA
            sys.exit(0)
            
        controlador = ControladorFiscal()
        controlador.LanzarExcepciones = True

        marca = conf.get("marca", "epson")
        modelo = conf.get("modelo", "epsonlx300+")
        puerto = conf.get("puerto", "COM2")
        equipo = conf.get("equipo", "")
        controlador.Conectar(marca, modelo, puerto, equipo)

        if '--ult' in sys.argv:
            print "Consultar ultimo numero:"
            i = sys.argv.index("--ult")
            if i+1 < len(sys.argv):
               tipo_cbte = int(sys.argv[i+1])
            else:
               tipo_cbte = int(raw_input("Tipo de comprobante: ") or 83)
            ult = controlador.ConsultarUltNro(tipo_cbte)
            print "Ultimo Nro de Cbte:", ult

        if '--prueba' in sys.argv:
            # creo una factura de ejemplo
            tipo_cbte = 6
            tipo_doc = 80; nro_doc = "20267565393"
            nombre_cliente = 'Joao Da Silva'
            domicilio_cliente = 'Rua 76 km 34.5 Alagoas'
            tipo_responsable = 5
            referencia = None
            
            ok = controlador.AbrirComprobante(tipo_cbte, tipo_responsable, 
                                            tipo_doc, nro_doc,
                                            nombre_cliente, domicilio_cliente, 
                                            referencia)
            
            codigo = "P0001"
            ds = "Descripcion del producto P0001"
            qty = 1.00
            precio = 100.00
            bonif = 0.00
            alic_iva = 21.00
            importe = 121.00
            ok = controlador.ImprimirItem(ds, qty, importe, alic_iva)

            ok = controlador.ImprimirPago("efectivo", importe)
            ok = controlador.CerrarComprobante()
            

