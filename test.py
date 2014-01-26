# -*- coding: iso-8859-1 -*-

#printer = EpsonPrinter(deviceFile="/dev/ttyS0", model="tm-2000af+", dummy=True)
if 0:
    from epsonFiscal import EpsonPrinter
    print "Usando driver de Epson"
    printer = EpsonPrinter(deviceFile="/dev/ttyS0", model="615", dummy=True)
else:
    from hasarPrinter import HasarPrinter
    print "Usando driver de Hasar"
    printer = HasarPrinter(deviceFile="/dev/ttyS0", model="250", dummy=False)


number = printer.getLastNumber("B") + 1
print "imprimiendo la FC ", number
printer.openTicket()
# Caramelos a $ 1,50, con 21% de IVA, 2 paquetes de cigarrillos a $ 10
printer.addItem("CARAMELOS", 1, 1.50, 21, discount=0, discountDescription="")
printer.addItem("CIGARRILLOS", 2, 10, 21, discount=0, discountDescription="")
# Pago en efectivo. Si el importe fuera mayor la impresora va a
# calcular el vuelto
printer.addPayment("Efectivo", 11.5)
printer.closeDocument()


