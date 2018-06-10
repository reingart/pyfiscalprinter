#!/usr/bin/python
# -*- coding: utf8 -*-
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
__version__ = "1.06c"

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
  --ult: consulta y devuelve el último número de comprobante impreso
  --prueba: genera y autoriza una factura de prueba (no usar en producción!)

  --dbus: inicia el servicio y exporta el componente (Linux)
  --register: registra el componente (Windows)

Sin parámetros, se procesará el archivo de entrada (factura.json)

Ver fiscal.ini para parámetros de configuración "
"""

import codecs
import datetime
import decimal
import json
import os
import sys
import traceback
from cStringIO import StringIO
from decimal import Decimal
from functools import wraps

# Drivers:

from epsonFiscal import EpsonPrinter, EpsonExtPrinter
from hasarPrinter import HasarPrinter


try:
    import dbus, dbus.mainloop.glib
    import gobject
    from dbus.service import Object, method
except ImportError:
    dbus = None
    Object = object
    method = lambda *args, **kwargs: (lambda func: func)  # decorator


def inicializar_y_capturar_excepciones(func):
    "Decorador para inicializar y capturar errores"
    @wraps(func)
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


class PyFiscalPrinter(Object):
    "Interfaz unificada para imprimir facturas en controladores fiscales"
    _public_methods_ = ['Conectar',
                        'AbrirComprobante', 'CerrarComprobante',
                        'ImprimirItem', 'ImprimirPago', 'Subtotal',
                        'ConsultarUltNro', 'CierreDiario',
                        'FijarTextoCabecera', 'FijarTextoPie',
                        ]
    _public_attrs_ = ['Version', 'Excepcion', 'Traceback', 'LanzarExcepciones',
                    ]
        
    _reg_progid_ = "PyFiscalPrinter"
    _reg_clsid_ = "{4E214B11-424E-40F7-9869-680C9520125E}"
    DBUS_IFACE = 'ar.com.pyfiscalprinter.Interface'
    
    def __init__(self, session_bus=None, object_path=None):
        if dbus:
            Object.__init__(self, session_bus, object_path)
        self.Version = __version__
        self.factura = None
        self.Exception = self.Traceback = ""
        self.LanzarExcepciones = False
        self.printer = None
        self.log = StringIO()
        self.header = []
        self.trailer = []

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='ssss', out_signature='b')
    def Conectar(self, marca="epson", modelo="320", puerto="COM1", equipo=None):
        "Iniciar la comunicación con la instancia del controlador fiscal"
        if marca == 'epson':
            if modelo.upper() in ("TM-T900FA", ):
                # segunda generación (protocolo extendido):
                Printer = EpsonExtPrinter
            else:
                Printer = EpsonPrinter
        elif marca == 'hasar':
            Printer = HasarPrinter
        dummy = puerto == "dummy"
        # instanciar la impresora fiscal
        if not equipo:
            # conexión por puerto serie
            printer = Printer(deviceFile=puerto, model=modelo, dummy=dummy)
        else:
            # conexion por proxy TCP/IP
            printer = Printer(model=modelo, host=equipo, port=int(puerto), dummy=dummy)
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
        return True

    def DebugLog(self):
        "Devolver bitácora de depuración"
        msg = self.log.getvalue()
        return msg    

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='iiissss', out_signature='b')
    def AbrirComprobante(self, 
                         tipo_cbte=83,                              # tique
                         tipo_responsable=5,                        # consumidor final
                         tipo_doc=99, nro_doc=0,                    # sin especificar
                         nombre_cliente="", domicilio_cliente="",
                         referencia=None,                           # comprobante original (ND/NC)
                         **kwargs
                         ):
        "Creo un objeto factura (internamente) e imprime el encabezado"
        # crear la estructura interna
        self.factura = {"encabezado": dict(tipo_cbte=tipo_cbte,
                                           tipo_responsable=tipo_responsable,
                                           tipo_doc=tipo_doc, nro_doc=nro_doc,
                                           nombre_cliente=nombre_cliente, 
                                           domicilio_cliente=domicilio_cliente,
                                           referencia=referencia),
                        "items": [], "pagos": []}
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
        # enviar texto de cabecera y pie de pagina:
        ##printer.setHeader(self.header)
        ##printer.setTrailer(self.trailer)
        # enviar los comandos de apertura de comprobante fiscal:
        if cbte_fiscal.startswith('T'):
            if letra_cbte:
                ret = printer.openTicket(letra_cbte)
            else:
                ret = printer.openTicket()
        elif cbte_fiscal.startswith("F"):
            params = {}
            if "remitos" in kwargs:
                params["remits"] = kwargs["remitos"]
            ret = printer.openBillTicket(letra_cbte, nombre_cliente, domicilio_cliente, 
                                         nro_doc, doc_fiscal, pos_fiscal, **params)
        elif cbte_fiscal.startswith("ND"):
            ret = printer.openDebitNoteTicket(letra_cbte, nombre_cliente, 
                                              domicilio_cliente, nro_doc, doc_fiscal, 
                                              pos_fiscal)
        elif cbte_fiscal.startswith("NC"):
            if isinstance(referencia, unicode):
                referencia = referencia.encode("latin1", "ignore")
            ret = printer.openBillCreditTicket(letra_cbte, nombre_cliente, 
                                               domicilio_cliente, nro_doc, doc_fiscal, 
                                               pos_fiscal, referencia)
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='vvvv', out_signature='b')
    def ImprimirItem(self, ds, qty, importe, alic_iva=21.):
        "Envia un item (descripcion, cantidad, etc.) a una factura"
        self.factura["items"].append(dict(ds=ds, qty=qty, 
                                          importe=importe, alic_iva=alic_iva))
        ##ds = unicode(ds, "latin1") # convierto a latin1
        # Nota: no se calcula neto, iva, etc (deben venir calculados!)
        discount = discountDescription =  None
        self.printer.addItem(ds, float(qty), float(importe), float(alic_iva), 
                                    discount, discountDescription)
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='vv', out_signature='b')
    def ImprimirPago(self, ds, importe):
        "Imprime una linea con la forma de pago y monto"
        self.factura["pagos"].append(dict(ds=ds, importe=importe))
        self.printer.addPayment(ds, float(importe))
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='', out_signature='b')
    def Subtotal(self, imprimir=True):
        "Devuelve el subtotal y lo imprime (opcional)"
        ret = self.printer.subtotal(imprimir)
        print ret
        if len(ret) == 10:      # epson
            qty = int(ret[3])
            subtotal = str(decimal.Decimal(ret[4]) / decimal.Decimal("100.000"))
            imp_iva = str(decimal.Decimal(ret[5]) / decimal.Decimal("100.000"))
        elif len(ret) == 8:     # hasar
            qty = ret[2]
            subtotal = ret[3]
            imp_iva = ret[4]
        self.factura["subtotal"] = subtotal
        self.factura["imp_iva"] = imp_iva
        self.factura["qty"] = qty
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='', out_signature='b')
    def CerrarComprobante(self):
        "Envia el comando para cerrar un comprobante Fiscal"
        nro = self.printer.closeDocument()
        self.factura["nro_cbte"] = nro
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='v', out_signature='i')
    def ConsultarUltNro(self, tipo_cbte):
        "Devuelve el último número de comprobante"
        # mapear el numero de documento según RG1361
        cbte_fiscal = self.cbte_fiscal_map[int(tipo_cbte)]
        letra_cbte = cbte_fiscal[-1] if len(cbte_fiscal) > 1 else None
        if cbte_fiscal.startswith("NC"):
            return self.printer.getLastCreditNoteNumber(letra_cbte)
        else:
            return self.printer.getLastNumber(letra_cbte)

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='s', out_signature='i')
    def CierreDiario(self, tipo):
        "Realiza el cierre diario, reporte Z o X"
        return self.printer.dailyClose(tipo)

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='vi', out_signature='b')
    def FijarTextoCabecera(self, ds, linea=None):
        if linea:
            self.header[linea] = ds
        else:
            self.header.append(ds)
        return True

    @inicializar_y_capturar_excepciones
    @method(DBUS_IFACE, in_signature='vi', out_signature='b')
    def FijarTextoPie(self, ds, linea=None):
        if linea:
            self.trailer[linea] = ds
        else:
            self.trailer.append(ds)
        return True


if __name__ == '__main__':

    if "--register" in sys.argv or "--unregister" in sys.argv:
        import win32com.server.register
        win32com.server.register.UseCommandLine(PyFiscalPrinter)
    elif "--dbus" in sys.argv:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        session_bus = dbus.SessionBus()
        name = dbus.service.BusName("ar.com.pyfiscalprinter.Service", session_bus)
        object = PyFiscalPrinter(session_bus, '/ar/com/pyfiscalprinter/Object')
        mainloop = gobject.MainLoop()
        print "Running PyFiscalPrinter service."
        mainloop.run()
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
            
        controlador = PyFiscalPrinter()
        controlador.LanzarExcepciones = True

        marca = conf.get("marca", "epson")
        modelo = conf.get("modelo", "epsonlx300+")
        puerto = conf.get("puerto", "dummy")
        equipo = conf.get("equipo", "")
        controlador.Conectar(marca, modelo, puerto, equipo)

        if config.has_section('CABECERA'):
            for linea, ds in sorted(config.items('CABECERA')):
                controlador.FijarTextoCabecera(ds)
        if config.has_section('PIE'):
            for linea, ds in sorted(config.items('PIE')):
                controlador.FijarTextoPie(ds)

        if '--cierre' in sys.argv:
            i = sys.argv.index("--cierre")
            if i+1 < len(sys.argv):
               tipo = sys.argv[i+1]
            else:
               tipo = raw_input("Tipo de cierre: ") or "Z"
            print "CierreDiario:", controlador.CierreDiario(tipo.upper())
        
        elif '--ult' in sys.argv:
            print "Consultar ultimo numero:"
            i = sys.argv.index("--ult")
            if i+1 < len(sys.argv):
               tipo_cbte = int(sys.argv[i+1])
            else:
               tipo_cbte = int(raw_input("Tipo de comprobante: ") or 83)
            ult = controlador.ConsultarUltNro(tipo_cbte)
            print "Ultimo Nro de Cbte:", ult

        elif '--prueba' in sys.argv:
            # creo una factura de ejemplo
            tipo_cbte = 83 if not "--nc" in sys.argv else 3
            tipo_doc = 80; nro_doc = "20267565393"
            nombre_cliente = 'Joao Da Silva'
            domicilio_cliente = 'Rua 76 km 34.5'
            tipo_responsable = 5 if not "--nc" in sys.argv else 1   # R.I. ("A)
            referencia = None if not "--nc" in sys.argv else "F 1234"
            
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
            
            with open(conf.get("entrada", "factura.json"), "w") as f:
                f = codecs.getwriter(conf.get("encoding", "utf8"))(f)
                json.dump(controlador.factura, f, 
                          indent=4, separators=(',', ': '))

        else:
            # leer y procesar una factura en formato JSON
            print("Iniciando procesamiento...")
            with open(conf.get("entrada", "factura.json"), "r") as f:
                f = codecs.getreader(conf.get("encoding", "utf8"))(f)
                factura = json.load(f)
            ok = controlador.AbrirComprobante(**factura["encabezado"])
            for item in factura["items"]:
                ok = controlador.ImprimirItem(**item)
            if "subtotal" in factura:
                ok = controlador.Subtotal(imprimir=factura["subtotal"]) 
            for pago in factura["pagos"]:
                ok = controlador.ImprimirPago(**pago)
            ok = controlador.CerrarComprobante()
            if ok:
                print "Nro. Cbte. impreso:", controlador.factura["nro_cbte"]
                if "subtotal" in factura:
                    print "Cant.Articulos:", controlador.factura["qty"]
                    print "Subtotal:", controlador.factura["subtotal"]  
                    print "IVA liq.:", controlador.factura["imp_iva"]

            with open(conf.get("salida", "factura.json"), "w") as f:
                f = codecs.getwriter(conf.get("encoding", "utf8"))(f)
                json.dump(controlador.factura, f, 
                          indent=4, separators=(',', ': '))
            print "Hecho."

