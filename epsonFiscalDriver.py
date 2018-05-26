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

    def _escape(self, field):
        "Escapar caracteres especiales (STX, ETX, ESC, FS)"
        ret = []
        for char in field:
            if ord(char) in (0x02, 0x03, 0x1b, 0x1c, ):
                 ret.append(chr(0x1b))                    # agregar escape
            ret.append(char)
        return "".join(ret)

class EpsonChileFiscalDriver(EpsonFiscalDriver):
    
    returnErrors = {
                        0: "Correcto",
                        1: "Error Interno",
                        2: "Error de Inicializacion",
                        3: "Error de Proceso Interno",
                        257: "Estado Inválido",
                        258: "Documento Inválido",
                        259: "Requiere Modo Técnico",
                        260: "Requiere Jumper de Reset Off",
                        261: "Requiere Jumper de Reset On",
                        262: "Requiere Jumper de Intervención Off",
                        263: "Requiere Jumper de Intervención On",
                        513: "Frame de Comando Inválido",
                        514: "Comando Inválido",
                        515: "Campos en Exceso",
                        516: "Campos en Defecto",
                        517: "Campo no Opcional",
                        518: "Campo Alfanumérico Inválido",
                        519: "Campo Alfabetico Inválido",
                        520: "Campo Numerico Inválido",
                        521: "Campo Binario Inválido",
                        522: "Campo Imprimible Inválido",
                        523: "Campo Hexadecimal Inválido",
                        524: "Campo de Fecha Inválido",
                        525: "Campo de Hora Inválido",
                        526: "Campo de Texto Enriquecido Inválido",
                        527: "Campo Booleano Inválido",
                        528: "Largo del Campo Inválido",
                        529: "Extension del Comando Inválida",
                        530: "El Campo no Soporta Código de Barras",
                        531: "El Campo no Soporta Atributos",
                        532: "Atributo Inválido",
                        533: "Dato de Código de barra Inválido",
                        769: "Error de Hardware",
                        770: "Impresora Fuera de Linea",
                        771: "Error de Impresion",
                        772: "Problemas de Papel",
                        773: "Poco Papel Disponible",
                        774: "Error al Cargar/Expulsar Papel",
                        775: "Caracteristica de impresora no soportada",
                        776: "Error Display",
                        777: "Secuencia de escaneo Inválida",
                        778: "Area de recorte Inválida",
                        779: "Escaner no listo",
                        1025: "Numero de Serie Inválido",
                        1026: "Datos Fiscales no Seteados",
                        1283: "Fecha/Hora Fuera de Rango",
                        1284: "Razon Social Inválida",
                        1285: "Punto de Venta Inválido",
                        1286: "RUT Inválido",
                        1288: "Numero de Encabezado/Cola Inválido",
                        1289: "Exceso de Fiscalizaciones",
                        1292: "Exceso de Tipos de Pago",
                        1293: "Tipo de Pago ya Definido",
                        1294: "Tipo de Pago Inválido",
                        1295: "Desc. del Tipo de Pago Inválida",
                        1296: "Porcentaje de Max.Desc. Inválido",
                        1297: "Claves de EJ Inválidas",
                        1298: "Claves EJ no Seteadas",
                        1299: "Datos de Logo Inválido",
                        2049: "Requiere Jornada Fiscal Abierta",
                        2050: "Requiere Jornada Fiscal Cerrada",
                        2051: "Memoria Fiscal Completa",
                        2052: "Se Requiere un Cierre Z",
                        2053: "Requiere Tipos de Pago Definidos",
                        2054: "Exceso de Tipo de Pagos por Jornada",
                        2055: "No hay datos",
                        2305: "Overflow",
                        2306: "Underflow",
                        2307: "Exceso de Items",
                        2308: "Exceso de Tasas de Impuesto",
                        2309: "Exceso de Descuentos/Recargos",
                        2310: "Exceso de Pagos",
                        2311: "Item no Localizado",
                        2312: "Pago no Localizado",
                        2313: "Total no puede ser Cero",
                        2316: "Tipo de Pago no Definido",
                        2317: "Exceso de Donaciones",
                        2318: "Donación no Localizada",
                        2561: "No Permitido luego de Descuentos/Recargos",
                        2562: "No Permitido luego de Fase de Pago",
                        2563: "Tipo de Item Inválido",
                        2564: "Descripcion no puede ser Nula",
                        2565: "Cantidad del Item (underflow)",
                        2566: "Cantidad del Item (overflow)",
                        2567: "Item Total (overflow)",
                        2568: "No Permitido antes de Fase de Pago",
                        2569: "Fase de Pago no Terminada",
                        2570: "Fase de Pago Terminada",
                        2571: "Monto de Pago no permitido",
                        2572: "Monto de Desc./Rec no permitido",
                        2573: "Valor de Donación no permitido",
                        2574: "Vuelto no es mayor a cero",
                        3585: "Exceso de lineas de texto NF",
                        65535: "Error Desconocido"
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
    REPLY_MAP = {"CommandNumber": 2, "StatPrinter": 0, "StatFiscal": 1, "Return": 3}
    STAT_FN = lambda self, x: struct.unpack(">H", x)[0] # convertir de unsigned short
    
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
        comandoEjecutado = fields[self.REPLY_MAP["CommandNumber"]] 
        print 'comandoEjecutado=',comandoEjecutado
        if comandoEjecutado=='\x00\x01':
            returnErrorsIndex = self.STAT_FN( fields[self.REPLY_MAP["Return"]] )
            print 'returnErrorsIndex=',returnErrorsIndex
            if returnErrorsIndex not in self.returnErrors.keys(): 
                self.returnErrors[returnErrorsIndex] = 'Error desconocido...'
            raise ReturnError, self.returnErrors[returnErrorsIndex]
        # elimino el numero de comando (por compatibilidad con Epson Arg.)
        if "CommandNumber" in self.REPLY_MAP:
            fields.pop(self.REPLY_MAP["CommandNumber"])
        return fields

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

