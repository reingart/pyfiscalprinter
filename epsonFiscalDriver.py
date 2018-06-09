# -*- coding: iso-8859-1 -*-
import serial
import random
import time
import sys
import SocketServer
import socket
import struct
import traceback

def debugEnabled( *args ):
    print >>sys.stderr, " ".join( map(str, args) )

def debugDisabled( *args ):
    pass

debug = debugEnabled

class PrinterException(Exception):
    pass

class UnknownServerError(PrinterException):
    errorNumber = 1

class ComunicationError(PrinterException):
    errorNumber = 2

class PrinterStatusError(PrinterException):
    errorNumber = 3

class FiscalStatusError(PrinterException):
    errorNumber = 4

ServerErrors = [UnknownServerError, ComunicationError, PrinterStatusError, FiscalStatusError]

class ProxyError(PrinterException):
    errorNumber = 5

class ReturnError(PrinterException): 
    errorNumber = 6

class SerialPortSimulator:
    "Fake file-like for testing"
    
    def __init__(self):
        self.rd = open("fiscal_in.bin", "rb")
        self.wr = open("fiscal_out.bin", "wb")

    def read(self, *args, **kwargs):
        s = self.rd.read(*args, **kwargs)
        print "read() -> %s" % "".join(["%02x" % ord(c) for c in s])
        if not s:
            raise RuntimeError("no mas datos")
        return s
    
    def write(self, s, *args, **kwargs):
        print "write(%s)" % "".join(["%02x" % ord(c) for c in s])
        return self.wr.write(s, *args, **kwargs)

    def close(self):
        self.rd.close()
        self.wr.close() 


class EpsonFiscalDriver:
    WAIT_TIME = 10
    RETRIES = 4
    WAIT_CHAR_TIME = 0.1
    NO_REPLY_TRIES = 200
    CMD_FMT = lambda self, x: chr(x)
    MIN_SEQ = 0x20
    MAX_SEQ = 0x7f
    ACK = None #chr(0x06)
    NAK = chr(0x15)
    REPLY_MAP = {"CommandNumber": 0, "StatPrinter": 1, "StatFiscal": 2}
    ESCAPE_CHARS = (0x02, 0x03, 0x1b, 0x1c, )

    fiscalStatusErrors = [#(1<<0 + 1<<7, "Memoria Fiscal llena"),
                          (1<<0, "Error en memoria fiscal"),
                          (1<<1, "Error de comprobación en memoria de trabajo"),
                          (1<<2, "Poca batería"),
                          (1<<3, "Comando no reconocido"),
                          (1<<4, "Campo de datos no válido"),
                          (1<<5, "Comando no válido para el estado fiscal"),
                          (1<<6, "Desbordamiento de totales"),
                          (1<<7, "Memoria Fiscal llena"),
                          (1<<8, "Memoria Fiscal casi llena"),
                          (1<<11, "Es necesario hacer un cierre de la jornada fiscal o se superó la cantidad máxima de tickets en una factura."),
                          ]

    printerStatusErrors = [(1<<2, "Error y/o falla de la impresora"),
                          (1<<3, "Impresora fuera de linea"),
##                          (1<<4, "Poco papel para la cinta de auditoría"),
##                          (1<<5, "Poco papel para comprobantes o tickets"),
                          (1<<6, "Buffer de impresora lleno"),
                          (1<<14, "Impresora sin papel"),
                          ]

    def __init__( self, deviceFile, speed = 9600 ):
        if deviceFile:
            self._serialPort = serial.Serial( port = deviceFile, timeout = None, baudrate = speed )
        else:
            self._serialPort = SerialPortSimulator()
        self._initSequenceNumber()

    def _initSequenceNumber( self ):
        self._sequenceNumber = random.randint( self.MIN_SEQ, self.MAX_SEQ )

    def _incrementSequenceNumber( self ):
        # Avanzo el número de sequencia, volviendolo al inicio si pasó el limite
        if self._sequenceNumber < self.MAX_SEQ:
            self._sequenceNumber += 1
        else:
            self._sequenceNumber = self.MIN_SEQ

    def _write( self, s ):
        if isinstance(s, unicode):
            s = s.encode("latin1")
        debug( "_write", ", ".join( [ "%x" % ord(c) for c in s ] ) )
        self._serialPort.write( s )

    def _read( self, count ):
        ret = self._serialPort.read( count )
        debug( "_read", ", ".join( [ "%x" % ord(c) for c in ret ] ) )
        return ret

    def __del__( self ):
        if hasattr(self, "_serialPort" ):
            try:
                self.close()
            except:
                pass

    def close( self ):
        try:
            self._serialPort.close()
        except:
            pass
        del self._serialPort

    def sendCommand( self, commandNumber, fields, skipStatusErrors = False ):
        message = chr(0x02) + chr( self._sequenceNumber ) + self._escape(self.CMD_FMT(commandNumber))
        if fields:
            message += chr(0x1c)
        message += chr(0x1c).join([self._escape(field) for field in fields])
        message += chr(0x03)
        checkSum = sum( [ord(x) for x in message ] )
        checkSumHexa = ("0000" + hex(checkSum)[2:])[-4:].upper()
        message += checkSumHexa
        reply = self._sendMessage( message )
        self._incrementSequenceNumber()
        return self._parseReply( reply, skipStatusErrors )

    def _parseReply( self, reply, skipStatusErrors ):
        r = reply[2:-1] # Saco STX <Nro Seq> ... ETX
        fields = r.split( chr(28) )
        field = [self._escape(field) for field in fields]
        printerStatus = fields[self.REPLY_MAP["StatPrinter"]]
        fiscalStatus = fields[self.REPLY_MAP["StatFiscal"]]
        if not skipStatusErrors:
            self._parsePrinterStatus( printerStatus )
            self._parseFiscalStatus( fiscalStatus )
        # elimino el numero de comando (por compatibilidad con Epson Arg.)
        if "CommandNumber" in self.REPLY_MAP:
            fields.pop(self.REPLY_MAP["CommandNumber"])
        return fields

    def _parsePrinterStatus( self, printerStatus ):
        x = self.STAT_FN(printerStatus)
        for value, message in self.printerStatusErrors:
            if (value & x) == value:
                raise PrinterStatusError, message

    def _parseFiscalStatus( self, fiscalStatus ):
        x = self.STAT_FN(fiscalStatus)
        for value, message in self.fiscalStatusErrors:
            if (value & x) == value:
                raise FiscalStatusError, message

    def _sendMessage( self, message ):
        # Envía el mensaje
        # @return reply Respuesta (sin el checksum)
        self._write( message )
        timeout = time.time() + self.WAIT_TIME
        retries = 0
        while 1:
            if time.time() > timeout:
                raise ComunicationError, "Expiró el tiempo de espera para una respuesta de la impresora. Revise la conexión."
            c = self._read(1)
            if len(c) == 0:
                continue
            if ord(c) in (0x12, 0x14): # DC2 o DC4
                # incrementar timeout
                timeout += self.WAIT_TIME
                continue
            # TODO: verificar ACK
            if ord(c) == 0x15: # NAK
                if retries > self.RETRIES:
                    raise ComunicationError, "Falló el envío del comando a la impresora luego de varios reintentos"
                # Reenvío el mensaje
                self._write( message )
                timeout = time.time() + self.WAIT_TIME
                retries +=1
                continue
            if c == chr(0x02):# STX - Comienzo de la respuesta
                reply = c
                noreplyCounter = 0
                while c != chr(0x03): # ETX (Fin de texto)
                    c = self._read(1)
                    # TODO: soportar ESC y cantidad mínima de bytes por campo obligatorio
                    if not c:   
                        noreplyCounter += 1
                        time.sleep(self.WAIT_CHAR_TIME)
                        if noreplyCounter > self.NO_REPLY_TRIES:
                            raise ComunicationError, "Fallo de comunicación mientras se recibía la respuesta de la impresora."
                    else:
                        noreplyCounter = 0
                        reply += c
                bcc = self._read(4) # Leo BCC
                if not self._checkReplyBCC( reply, bcc ):
                    # Mando un NAK y espero la respuesta de nuevo.
                    self._write( chr(0x15) )
                    timeout = time.time() + self.WAIT_TIME
                    retries += 1
                    if retries > self.RETRIES:
                        raise ComunicationError, "Fallo de comunicación, demasiados paquetes inválidos (bad bcc)."
                    continue
                elif self._checkReplyInter( reply ):
                    # respuesta intermedia transcurridos 500ms
                    # no es necesario enviar una confirmación (ACK/NACK)
                    timeout += self.WAIT_CHAR_TIME * 5
                    continue
                elif reply[1] != chr( self._sequenceNumber ): # Los número de seq no coinciden
                    # Reenvío el mensaje
                    self._write( message )
                    timeout = time.time() + self.WAIT_TIME
                    retries +=1
                    if retries > self.RETRIES:
                        raise ComunicationError, "Fallo de comunicación, demasiados paquetes inválidos (mal sequence_number)."
                    continue
                else:
                    # Respuesta OK
                    if self.ACK:
                        self._write( self.ACK )
                    break
        return reply

    def _checkReplyBCC( self, reply, bcc ):
        debug( "reply", reply, [ord(x) for x in reply] )
        checkSum = sum( [ord(x) for x in reply ] )
        debug( "checkSum", checkSum )
        checkSumHexa = ("0000" + hex(checkSum)[2:])[-4:].upper()
        debug( "checkSumHexa", checkSumHexa )
        debug( "bcc", bcc )
        return checkSumHexa == bcc.upper()

    def _checkReplyInter( self, reply ):
        return False

    def _escape(self, field):
        "Escapar caracteres especiales (STX, ETX, ESC, FS)"
        ret = []
        if not isinstance(field, basestring):
            field = str(field)
        for char in field:
            if ord(char) in self.ESCAPE_CHARS:
                 ret.append(chr(0x1b))                    # agregar escape
            if isinstance(char, unicode):
                char = char.encode("latin1")
            ret.append(char)
        return "".join(ret)

class EpsonExtFiscalDriver(EpsonFiscalDriver):
    "Protocolo Extendido. Segunda Generación. Nueva Tecnología RG 3561/13 AFIP"
    
    returnErrors = {
                    0x0000: "Correcto",
                    0x0001: "Error Interno",
                    0x0002: "Error de inicializacion del equipo",
                    0x0003: "Error de Proceso Interno",
                    0x0101: "Comando inválido para el estado actual",
                    0x0102: "Comando inválido para el documento actual",
                    0x0103: "Comando sólo aceptado en modo técnico",
                    0x0104: "Comando sólo aceptado con Jumper de Servicio",
                    0x0105: "Comando sólo aceptado con Jumper de Servicio",
                    0x0106: "Comando sólo aceptado con Jumper de Uso Interno",
                    0x0107: "Comando sólo aceptado con Jumper de Uso Interno",
                    0x0108: "Sub estado Inválido",
                    0x0109: "Límite de intervenciones técnicas alcanzado",
                    0x010C: "Secuencia de descarga inválida",
                    0x0201: "El frame no contiene el largo mínimo aceptado",
                    0x0202: "Comando inválido",
                    0x0203: "Campos en Exceso",
                    0x0204: "Campos en Defecto",
                    0x0205: "Campo no Opcional",
                    0x0206: "Campo Alfanumérico Inválido",
                    0x0207: "Campo Alfabetico Inválido",
                    0x0208: "Campo Numerico Inválido",
                    0x0209: "Campo Binario Inválido",
                    0x020A: "Campo Imprimible Inválido",
                    0x020B: "Campo Hexadecimal Inválido",
                    0x020C: "Campo de Fecha Inválido",
                    0x020D: "Campo de Hora Inválido",
                    0x020E: "Campo de Texto Enriquecido Inválido",
                    0x020F: "Campo Booleano Inválido",
                    0x0210: "Largo del Campo Inválido",
                    0x0211: "Extension del Comando Inválida",
                    0x0212: "El Campo no Soporta Código de Barras",
                    0x0213: "Atributos de impresión no permitidos",
                    0x0214: "Atributo de impresión Inválido",
                    0x0215: "Código de barra incorrectamente definido",
                    0x0216: "Combinación de la palabra 'total' no aceptada", 
                    0x0219: "Uno de dos campos es estrictamente opcional, nunca los dos juntos",
                    0x0250: "Error al descargar el reporte de eventos",
                    0x0251: "Secuencia de descarga del reporte de eventos inválida",
                    0x0301: "Error de Hardware",
                    0x0302: "Impresora Fuera de Linea",
                    0x0303: "Error de Impresion",
                    0x0304: "Problemas de Papel, no se encuentra en condiciones para realizar la acción requerida, verificar si hay papel en rollo, slip o validación al mismo tiempo",
                    0x0305: "Poco Papel Disponible",
                    0x0306: "Error al Cargar/Expulsar Papel",
                    0x0307: "Caracteristica de impresora no soportada",
                    0x0308: "Error Display",
                    0x0309: "Secuencia de escaneo Inválida",
                    0x030A: "Area de recorte Inválida",
                    0x030B: "Escaner no listo",
                    0x030C: "Resolución de logotipo de la empresa no permitida",
                    0x030D: "Imposible imprimir documento en estación térmica",
                    0x0401: "Numero de Serie Inválido",
                    0x0402: "Datos Fiscales no Seteados",
                    0x0404: "Aun no se realizó al menos uno de los dos tipo de descargas requeridas para las jornadas fiscales. Descarga completa o descarga de documentos tipo A",
                    0x0405: "Las jornadas fiscales descargadas no se encuentran borradas",
                    0x0430: "Secuencia de solicicitud de certificado digital inválida",
                    0x0436: "Secuencia de carga de certificado digital inválida",
                    0x0437: "No se puede generar archivo CSR",
                    0x0438: "No se puede guardar archivo CRT",
                    0x0439: "Error interno en validación de certificado digital",
                    0x0440: "Certificado aún no vigente",
                    0x043A: "Tipo de certificado digital inválido",
                    0x043B: "No se puede validar el certificado digital",
                    0x043C: "Certificado AFIP no encontrado",
                    0x043D: "Cadena de certificados no encontrada",
                    0x043E: "Certificado Digital CF aún válido (CF.:Controlador Fiscal)",
                    0x043F: "Certificado Digital CF vencido (CF.:Controlador Fiscal)",
                    0x0441: "Secuencia de descarga SAF inválida",
                    0x0442: "Falla al crear archivo SAF",
                    0x0450: "Error en el XML",
                    0x0451: "Número de bajas fiscales no coincide",
                    0x0452: "Demasiados cambios de CUIT",
                    0x0453: "Imposible descargar el archivo de solicitud de baja fiscal (SFB), ya que no existe una baja fiscal previamente", 
                    0x0454: "Ocurrió algún error al intentar descargar el archivo de solicitud de baja fiscal (SFB)", 
                    0x0455: "Imposible copiar certificado de cadena ya instalado al directorio temporal",
                    0x0456: "Certificado/s de cadena no instalado/s",
                    0x0501: "Fecha / Hora no configurada",
                    0x0502: "Error en cambio de fecha",
                    0x0503: "Fecha fuera de rango",
                    0x0505: "Número de caja inválido",
                    0x0506: "CUIT inválido",
                    0x0507: "Responsabilidad frente al IVA inválida",
                    0x0508: "Número de línea de Encabezado/Cola inválido",
                    0x0509: "Demasiadas fiscalizaciones",
                    0x050A: "Demasiados cambios de situación tributaria",
                    0x050B: "Demasiados cambios de datos de fiscalización",
                    0x0513: "Logo de usuario inválido",
                    0x0514: "Secuencia de definición de logos de usuario inválida",
                    0x0515: "Configuración de Display inválida",
                    0x0516: "Tipo de letra de MICR inválida",
                    0x0518: "Líneas de establecimiento no configuradas",
                    0x0519: "Datos fiscales no configurados",
                    0x0520: "Situación tributaria no configurada",
                    0x0521: "Tasa de IVA estándar no configurada",
                    0x0522: "Límite de tique-factura no configurado",
                    0x0524: "Monto máximo de tique-factura no permitido",
                    0x0525: "Largo del logotipo de la empresa no permitido",
                    0x0526: "Posición del logotipo de la empresa inválido",
                    0x0527: "El tamaño del logotipo de la empresa excede el máximo",
                    0x0550: "Identificador tributario ya estaba configurado",
                    0x0555: "Cambio de horario de verano no permitido",
                    0x0556: "Formato o rango, de la línea de inicio de actividades, inválido",
                    0x0601: "Memoria de transacciones llena",
                    0x0604: "Rango de auditoría solicitado sin datos",
                    0x0801: "Requiere período de actividades iniciado",
                    0x0802: "Require un Cierre Z",
                    0x0803: "Memoria fiscal llena",
                    0x0804: "Requiere jornada fiscal abierta",
                    0x0807: "Período auditado sin datos",
                    0x0808: "Rango auditado inválido",
                    0x0809: "Restan datos por auditar/descargar",
                    0x080A: "No hay más datos a descargar",
                    0x080B: "No es posible abrir la jornada fiscal",
                    0x080C: "No es posible cerrar la jornada fiscal",
                    0x0810: "Tipo de documento solicitado inválido",
                    0x0811: "Número de documento solicitado inválido",
                    0x0812: "Documento solicitado no existente",
                    0x0813: "La copia del documento solicitado fue borrada",
                    0x0814: "Tipo de documento no soportado",
                    0x0815: "Registrado para emitir documentos 'normales'",
                    0x0816: "Registrado para emitir documentos 'M'",
                    0x0817: "Falta descargar jornadas previas",
                    0x0818: "Sólo se puede imprimir el cambio una única vez dentro de la jornada",
                    0x0819: "Requiere que se encuentre establecida la línea de inicio de actividades",
                    0x0901: "Overflow",
                    0x0902: "Underflow",
                    0x0903: "Demasiados ítems involucrados en la transacción",
                    0x0904: "Demasiadas tasas de impuesto utilizadas",
                    0x0905: "Demasiados descuentos / ajustes sobre subtotal involucradas en la transacción",
                    0x0906: "Demasiados pagos involucrados en la transacción",
                    0x0907: "Item no encontrado",
                    0x0908: "Pago no encontrado",
                    0x0909: "El total debe ser mayor a cero",
                    0x090A: "Se permite sólo un tipo de impuestos internos",
                    0x090B: "Impuesto interno no aceptado",
                    0x090F: "Tasa de IVA no encontrada",
                    0x0910: "Tasa de IVA inválida",
                    0x091E: "Período descargado demasiado grande",
                    0x0A01: "No permitido luego de descuentos / ajustes sobre el subtotal",
                    0x0A02: "No permitido luego de iniciar la fase de pago",
                    0x0A03: "Tipo de ítem inválido",
                    0x0A04: "Línea de descripción en blanco",
                    0x0A05: "Cantidad resultante menor que cero",
                    0x0A06: "Cantidad resultante mayor a lo permitido",
                    0x0A07: "Precio total del ítem mayor al permitido",
                    0x0A0A: "Fase de pago finalizada",
                    0x0A0B: "Monto de pago no permitido",
                    0x0A0C: "Monto de descuento / ajuste no permitido",
                    0x0A0F: "No permitido antes de un ítem",
                    0x0A10: "Demasiadas descripciones extras",
                    0x0A31: "Código de tipo de pago inválido",
                    0x0A32: "Imposible aplicar el descuento/ajuste particular. No se encontró un ítem que corresponda a la misma tasa de IVA y código de condición frente al IVA",
                    0x0A33: "Operación no permitida luego de Otros tributos",
                    0x0A34: "Otros tributos del tipo percepciones no soportado en Tique y Tique Nota de Crédito",
                    0x0B01: "Tipo de documento del comprador inválido",
                    0x0B02: "Máximo valor aceptado fue superado",
                    0x0B03: "CUIT/CUIL inválido",
                    0x0B04: "Tipo de otros tributo inválido",
                    0x0B05: "Exceso en la cantidad de líneas de separación de la firma",
                    0x0B06: "Monto cero de otros tributos no permitido",
                    0x0B07: "Demasiados Otros Tributos involucradas en la transacción",
                    0x0B08: "Otro tributo no encontrado",
                    0x0B09: "Operación no permitida luego de Otros Tributos",
                    0x0B0A: "Exceso de operaciones dentro del documento con triplicado",
                    0x0B0B: "Tique factura del turista solo es aceptado en tique-factura B",
                    0x0B0C: "Datos del turista inválidos",
                    0x0B0D: "Número de documento inválido",
                    0x0B0E: "Documento no soportado por el mecanismo de impresión",
                    0x0B11: "Tipo de documento asociado inválido",
                    0x0B12: "Punto de venta de documento asociado inválido",
                    0x0B13: "Número de documento asociado inválido",
                    0x0B14: "Otros tributos no soportado en Donaciones y Remito X/R",
                    0x0B15: "Número (#) de otros tributos con valor cero no permitido",
                    0x0B16: "Número (#) de otros tributos inválido",
                    0x0B17: "No existen otros tributos",
                    0x0B18: "Número de CUIT inválido para transportista, al emitir Remito X/R",
                    0x0B19: "Tipo de documento del tercero inválido",
                    0x0B1A: "CUIT/CUIL del tercero inválido",
                    0x0B1B: "Tipo de documento del beneficiario/chofer inválido",
                    0x0B1C: "CUIT/CUIL del beneficiario/chofer inválido",
                    0x0B1D: "Responsabilidad frente al IVA del tercero inválida",
                    0x0E02: "Exceso de código de barras dentro del documento",
                    0x1003: "Error interno al sumar monto de importe en un DNFH",
                    0x1004: "Pagos no soportado en DNFH Presupuesto X, Remito R/X",
                    0x1005: "Tipo de ítem no soportado en DNFH Remito R/X, Recibo X o Donaciones ",
                    0x1006: "Descuentos/Recargos no permitido en DNFH Remito R/X, Recibo X o Donaciones",
                    0x1007: "Solamente se soporta un único ítem en Donaciones",
                    0x1008: "La cantidad del item debe ser uno en Donaciones y Recibo X",
                    0x1014: "Otros tributos no soportado en Donaciones y Remito X/R",
                    0x1015: "La razón social, el domicilio y el tipo y número de del beneficiario, son requeridos en Donaciones",
                    0x2005: "Código de unidad de medida reservado",
                    0x2006: "Código de condición frente al IVA inválido",
                    0x2007: "Sólo se permite una Condición frente al IVA del tipo Gravado (observar que la tasa de IVA es distinto de Cero)",
                    0x2008: "Código de otros tributos inválido",
                    0x2009: "Código de otros tributos no permitido",
                    0x7001: "Cable de red desconectado",
                    0x7002: "Dirección IP inválida",
                    0x7003: "Máscara de red inválida",
                    0x7004: "Dirección de puerta de enlace predeterminada inválida",
                    0x7005: "Error en DHCP",
                    0x7006: "Error al aplicar la configuración",
                    0xFFFF: "Error Desconocido"
                    }
    printerStatusErrors = [
                        (1<<15, "Impresora Offline."),
                        (1<<14, "Impresora con Error."),
                        (1<<13, "Tapa de la impresora abierta"),
                        (1<<12, "Cajón de dinero abierto."),
                        (1<<3, "Papel no disponible."),
                        (1<<2, "Poco papel disponible."),
                    ]

    WAIT_TIME = 10
    RETRIES = 4
    WAIT_CHAR_TIME = 0.1
    NO_REPLY_TRIES = 200
    CMD_FMT = lambda self, x: struct.pack(">H", x) # unsigned short (network big-endian)
    MIN_SEQ = 0x81
    MAX_SEQ = 0xff
    RES_SEQ = 0x80      # Paquete de Respuesta Intermedia (no responder con ACK)
    ACK = chr(0x06)
    NAK = chr(0x15)
    REPLY_MAP = {"StatPrinter": 0, "StatFiscal": 1, "Return": 3}
    STAT_FN = lambda self, x: struct.unpack(">H", x)[0] # convertir de unsigned short
    ESCAPE_CHARS = (0x02, 0x03, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f)
    
    def _parseReply( self, reply, skipStatusErrors ):
        r = reply[2:-1] # Saco STX <Nro Seq> ... ETX
        fields = r.split( chr(28) )
        fields = [self._unescape(field) for field in fields]
        print 'fields=',fields
        printerStatus = fields[self.REPLY_MAP["StatPrinter"]]
        fiscalStatus = fields[self.REPLY_MAP["StatFiscal"]]
        if not skipStatusErrors:
            self._parsePrinterStatus( printerStatus )
            self._parseFiscalStatus( fiscalStatus )
        # Posición 'CommandNumber' retorna si el comando se ejecuto o no...
        # toma dos valores -> \x00\x01 = NO ejecutado | \x00\x00 = SI ejecutado
        returnErrorsIndex = self.STAT_FN( fields[self.REPLY_MAP["Return"]] )
        print 'returnErrorsIndex=',returnErrorsIndex
        # si no hubo error (0x0000), no lanzar excepción:
        if returnErrorsIndex:
            if returnErrorsIndex not in self.returnErrors.keys(): 
                self.returnErrors[returnErrorsIndex] = 'Error desconocido...'
            raise ReturnError, self.returnErrors[returnErrorsIndex]
        # elimino el numero de comando (por compatibilidad con Epson Arg.)
        if "CommandNumber" in self.REPLY_MAP:
            fields.pop(self.REPLY_MAP["CommandNumber"])
        return fields

    def _checkReplyInter( self, reply ):
        # verificar si es una respuesta intermedia (sin campos, seq especial)
        return reply[1] == chr( self.RES_SEQ )

    def _parseFiscalStatus( self, fiscalStatus ):
        # TODO: 
        fiscalStatus  = repr(fiscalStatus).replace('\\x','').replace("'",'') # \xc0\x80 a c080 viv
        binario = str(bin(int(fiscalStatus, 16))[2:].zfill(16)) #c080 a 1100000010000000 vivi
        print 'fiscalStatus=',fiscalStatus, binario
        if binario[-12]+binario[-11]=='10':
              raise FiscalStatusError, "Memoria fiscal llena."
        if binario[-12]+binario[-11]=='11':
              raise FiscalStatusError, "Memoria fiscal con desperfecto."

    def _unescape(self, field): 
        ret = []
        for char in field:
            if ord(char) != 0x1b:
                 ret.append(char)
        return "".join(ret)


class HasarFiscalDriver( EpsonFiscalDriver ):
    fiscalStatusErrors = [(1<<0 + 1<<7, "Memoria Fiscal llena"),
                          (1<<0, "Error en memoria fiscal"),
                          (1<<1, "Error de comprobación en memoria de trabajo"),
                          (1<<2, "Poca batería"),
                          (1<<3, "Comando no reconocido"),
                          (1<<4, "Campo de datos no válido"),
                          (1<<5, "Comando no válido para el estado fiscal"),
                          (1<<6, "Desbordamiento de totales"),
                          (1<<7, "Memoria Fiscal llena"),
                          (1<<8, "Memoria Fiscal casi llena"),
                          (1<<11, "Es necesario hacer un cierre de la jornada fiscal o se superó la cantidad máxima de tickets en una factura."),
                          ]

    printerStatusErrors = [(1<<2, "Error y/o falla de la impresora"),
                          (1<<3, "Impresora fuera de linea"),
##                          (1<<4, "Poco papel para la cinta de auditoría"),
##                          (1<<5, "Poco papel para comprobantes o tickets"),
                          (1<<6, "Buffer de impresora lleno"),
                          (1<<8, "Tapa de impresora abierta"),
                          ]

    ACK = chr(0x06)
    NAK = chr(0x15)
    STATPRN = chr(0xa1)

    def _initSequenceNumber( self ):
        self._sequenceNumber = random.randint( 0x20, 0x7f )
        if self._sequenceNumber % 2:
            self._sequenceNumber -= 1

    def _incrementSequenceNumber( self ):
        # Avanzo el número de sequencia, volviendolo a 0x20 si pasó el limite
        self._sequenceNumber += 2
        if self._sequenceNumber > 0x7f:
            self._sequenceNumber = 0x20

    def _sendAndWaitAck( self, message, count = 0 ):
        if count > 10:
            raise ComunicationError, "Demasiados NAK desde la impresora. Revise la conexión."
        self._write( message )
        timeout = time.time() + self.WAIT_TIME
        while 1:
            if time.time() > timeout:
                raise ComunicationError, "Expiró el tiempo de espera para una respuesta de la impresora. Revise la conexión."
            c = self._read(1)
            if len(c) == 0:
                continue
            if c == self.ACK:
                return True
            if c == self.NAK:
                return self._sendAndWaitAck( message, count + 1 )

    def _sendMessage( self, message ):
        # Envía el mensaje
        # @return reply Respuesta (sin el checksum)
        self._sendAndWaitAck( message )
        timeout = time.time() + self.WAIT_TIME
        retries = 0
        while 1:
            if time.time() > timeout:
                raise ComunicationError, "Expiró el tiempo de espera para una respuesta de la impresora. Revise la conexión."
            c = self._read(1)
            if len(c) == 0:
                continue
            if ord(c) in (0x12, 0x14): # DC2 o DC4
                # incrementar timeout
                timeout += self.WAIT_TIME
                continue
##            if ord(c) == self.NAK: # NAK
##                if retries > self.RETRIES:
##                    raise ComunicationError, "Falló el envío del comando a la impresora luego de varios reintentos"
##                # Reenvío el mensaje
##                self._write( message )
##                timeout = time.time() + self.WAIT_TIME
##                retries +=1
##                continue
            if c == chr(0x02):# STX - Comienzo de la respuesta
                reply = c
                noreplyCounter = 0
                while c != chr(0x03): # ETX (Fin de texto)
                    c = self._read(1)
                    if not c:
                        noreplyCounter += 1
                        time.sleep(self.WAIT_CHAR_TIME)
                        if noreplyCounter > self.NO_REPLY_TRIES:
                            raise ComunicationError, "Fallo de comunicación mientras se recibía la respuesta de la impresora."
                    else:
                        noreplyCounter = 0
                        reply += c
                bcc = self._read(4) # Leo BCC
                if not self._checkReplyBCC( reply, bcc ):
                    # Mando un NAK y espero la respuesta de nuevo.
                    self._write( self.NAK )
                    timeout = time.time() + self.WAIT_TIME
                    retries += 1
                    if retries > self.RETRIES:
                        raise ComunicationError, "Fallo de comunicación, demasiados paquetes inválidos (bad bcc)."
                    continue
                elif reply[1] != chr( self._sequenceNumber ): # Los número de seq no coinciden
                    # Reenvío el mensaje
                    self._write( self.ACK )
                    #self._sendAndWaitAck( message )
                    timeout = time.time() + self.WAIT_TIME
                    retries +=1
                    if retries > self.RETRIES:
                        raise ComunicationError, "Fallo de comunicación, demasiados paquetes inválidos (bad sequenceNumber)."
                    continue
                else:
                    # Respuesta OK
                    self._write( self.ACK )
                    break
        return reply

class DummyDriver:
    def close(self):
        pass

    def sendCommand(self, commandNumber, parameters, skipStatusErrors):
        print "%04x" % commandNumber, parameters, skipStatusErrors
        number = random.randint(0, 99999999)
        return ["00", "00"] + [str(number)] * 11

class EpsonFiscalDriverProxy:
    def __init__( self, host, port, timeout = 60.0, connectOnEveryCommand = False ):
        self.connectOnEveryCommand = connectOnEveryCommand
        self.timeout = timeout
        self.host = host
        self.port = port
        if not connectOnEveryCommand:
            self._connect()

    def _connect(self):
        self.socket = socket.socket()
        self.socket.settimeout( self.timeout )
        try:
            self.socket.connect( (self.host, self.port ) )
        except socket.error, e:
            raise ProxyError( "Error conectandose a la impresora remota: %s." % str(e) )
        self.socketFile = self.socket.makefile( "rw", 1 )

    def sendCommand( self, commandNumber, fields, skipStatusErrors = False ):
        if self.connectOnEveryCommand:
            self._connect()
            try:
                ret = self._sendCommand(commandNumber, fields, skipStatusErrors)
            finally:
                self.close()
        else:
            ret = self._sendCommand(commandNumber, fields, skipStatusErrors)
        return ret

    def _sendCommand( self, commandNumber, fields, skipStatusErrors = False ):
        commandStr = "0x" + ("%04x" % commandNumber).upper()
        self.socketFile.write( "SEND|%s|%s|%s\n" % (commandStr, skipStatusErrors and "T" or "F",
                                              fields) )
        reply = self.socketFile.readline()
        if reply[:5] == "REPLY":
            return eval( reply[7:] )
        elif reply[:5] == "ERROR":
            errorNum = int(reply[7:9])
            errorClass = filter( lambda x: x.errorNumber == errorNum, ServerErrors )
            if errorClass:
                raise errorClass[0]( reply[10:] )
            else:
                raise ProxyError( "Código de error desconocido: %s." % reply[7:] )
        else:
            raise ProxyError( "Respuesta no válida del servidor: %s." % reply )

    def close( self ):
        try:
            self.socket.close()
            del self.socket
        except:
            pass

    def __del__( self ):
        self.close()


def runServer( printerType, fileIn, fileOut, deviceFile, speed = 9600 ):
    if printerType == "Epson":
        p = EpsonFiscalDriver( deviceFile, speed )
    elif printerType == "Dummy":
        p = DummyDriver()
    else:
        p = HasarFiscalDriver( deviceFile, speed )
#    p = EpsonFiscalDriverProxy( 'localhost', 12345 )
    while 1:
        commandLine = fileIn.readline()
        if not commandLine:
            break
        # Formato de comandos:
        #  SEND|0x0042|F|["asdasd", "sdfs", "sdfsd"]
        #  012345678901234567890....
        send = commandLine[0:4]
        if send != "SEND":
            continue
        commandNumber = int(commandLine[5:11][2:], 16)
        skipStatusErrors = commandLine[12:13]
        skipStatusErrors = skipStatusErrors == "T" and True or False
        parameters = eval(commandLine[14:].strip())
        try:
            reply = p.sendCommand( commandNumber, parameters, skipStatusErrors )
        except PrinterException, e:
            fileOut.write( "ERROR: %02d %s\n" % (e.errorNumber, str(e)) )
        except Exception, e:
            fileOut.write( "ERROR: %02d %s\n" % (1, str(e)) )
        else:
            fileOut.write( "REPLY: %s\n" % reply )
        fileOut.flush()
    p.close()

class ReusableTCPServer(SocketServer.TCPServer):
    def server_bind(self):
        """Override server_bind to set socket options."""
        self.socket.setsockopt(socket.SOL_SOCKET,
            socket.SO_REUSEADDR, 1)
        return SocketServer.TCPServer.server_bind(self)


def socketServer(printerType, host, port, deviceFile, speed, timeout = 60, returnServer=False):
    class Handler( SocketServer.StreamRequestHandler ):
        rbufsize = 1
        wbufsize = 1
        def handle( self ):
            #self.connection.settimeout( timeout )
            return runServer( printerType, self.rfile, self.wfile, deviceFile, speed )

    server = ReusableTCPServer( (host, port), Handler )
    if returnServer:
    	return server
    server.serve_forever()


if __name__ == "__main__":
    from optparse import OptionParser
    parser = OptionParser( usage = "usage: \n  %prog ..." )

    parser.add_option( "-d", "--deviceFile", action = "store", type = "string",
                       dest = "deviceFile",
                       default = "/dev/ttyS0",
                       help = "Archivo de dispositivo del puerto serie para comunicar con la impresora." )
    parser.add_option( "-D", "--debug", action = "store_true",
                       dest = "debug",
                       default = False,
                       help = "Habilita salida de debug a stderr." )
    parser.add_option( "-s", "--speed", action = "store", type = "string",
                       dest = "speed", default = "9600",
                       help = "Velocidad de transferencia con el puerto serie." )
    parser.add_option( "-p", "--port", action = "store", type = "string",
                       dest = "port", default = None,
                       help = "Puerto donde escucha el server, si no se indica, la comunicación es por la entrada y salida estándar" )
    parser.add_option( "-i", "--ip", action = "store", type = "string",
                       dest = "ip", default = "",
                       help = "IP o Host donde escucha el server, si no se indica, la comunicación es por la entrada y salida estándar" )
    parser.add_option( "-t", "--printertype", action = "store", type = "string",
                       dest = "printerType", default = "Epson",
                       help = "Tipo de impresora. Hasar o Epson o Dummy. Default: Epson" )
    parser.add_option( "-T", "--timeout", action = "store", type = "string",
                       dest = "timeout", default = "60",
                       help = "Tiempo de espera antes de cancelar la conexión (en segundos). Default: 60 segundos" )
    (opts, args) = parser.parse_args()

    if opts.debug:
        debug = debugEnabled
    if opts.port:
        ret = socketServer( opts.printerType, opts.ip, int(opts.port), opts.deviceFile, int(opts.speed), int(opts.timeout) )
    else:
        ret = runServer( opts.printerType, sys.stdin, sys.stdout, opts.deviceFile, int(opts.speed) )
    sys.exit( ret )


# Formato de los comandos para enviar (tanto por socket como por linea de comandos):
# SEND|0x2a|F|["N"]
# Envía el comando 0x2a, El "F" es para skipStatusErrors, y los parámetros del comando: ["N"]

