# -*- coding: iso-8859-1 -*-

import sys

# Crear el controlador para la impresora fiscal:
if True or '--epsonext' in sys.argv:
    from epsonFiscal import EpsonExtPrinter
    print "Usando driver de Epson Protocolo Extendido (2da Gen)"
    model = ["TM-T900FA"][0]
    printer = EpsonExtPrinter(deviceFile="/dev/ttyUSB0", model=model, dummy=True)
elif False or '--epson' in sys.argv:
    from epsonFiscal import EpsonPrinter
    print "Usando driver de Epson"
    model = ["tickeadoras", "epsonlx300+", "tm-220-af"][1]
    printer = EpsonPrinter(deviceFile="COM2", model=model, dummy=False)
else:
    from hasarPrinter import HasarPrinter
    print "Usando driver de Hasar"
    model = ["615", "715v1", "715v2", "320"][0]
    printer = HasarPrinter(deviceFile="COM2", model=model, dummy=False)


number = printer.getLastNumber("B")+1
print "getLastNumber=", number
raw_input()

printReportX = printer.printReportX()
print "printReportX=", printReportX
raw_input()

# ticket -----------------------------

openTicket = printer.openTicket()
print "openTicket=", openTicket
raw_input()

addItem = printer.addItem('Nombre producto',1,100)
print "addItem=", addItem
raw_input()

infoTicket = printer.infoTicket()
print "infoTicket=", infoTicket
raw_input()

closeTicket = printer.closeTicket()
print "closeTicket=", closeTicket
raw_input()

# no fiscal -----------------------------

nofiscal = printer.openNonFiscalReceipt()
print "openNonFiscalReceipt=", nofiscal
raw_input()
nofiscal2 = printer.printNonFiscalText('algo')
print "printNonFiscalText=", nofiscal2
raw_input()
closelAnyDocument = printer.closelAnyDocument()
print "closelAnyDocument=", closelAnyDocument
raw_input()
