
' Ejemplo de Uso de Interface COM para imprimir en controladores fiscales
' homologados por AFIP en Argentina (Hasar, Epson y similares) utilizando
' intefaz PyFiscalPrinter: https://code.google.com/p/pyfiscalprinter/
' 2015 (C) Mariano Reingart <reingart@gmail.com>

' Registrar/iniciar python controlador.py --register (Windows)

Set fiscal = Wscript.CreateObject("PyFiscalPrinter")

''MsgBox "Ver:" & fiscal.Version, "PyFiscalPrinter"

' En VB 5/6 clasico usar: Set fiscal = CreateObject("PyFiscalPrinter")

marca = "hasar"            ' configurar "hasar" o "epson"
modelo = "320"     ' "tickeadoras", "epsonlx300+", "tm-220-af"
                           ' "615", "715v1", "715v2", "320"
puerto = "COM2"           ' "COM1", "COM2", etc.
equipo = ""                ' IP si no esta conectada a esta máquina

ok = fiscal.Conectar(marca, modelo, puerto, equipo)
    
' Analizar errores (si no se habilito lanzar excepciones)
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion: " + fiscal.Excepcion
End If

' Consultar el último número de comprobante impreso por el controlador:
' IMPORTANTE: en modo dummy solicita el número de comprobante por consola
tipo_cbte = 8
ult = fiscal.ConsultarUltNro(tipo_cbte)
MsgBox "Ultimo Nro de Cbte = " & ult

' Creo una factura de ejemplo:
tipo_cbte = 8                          ' factura B
tipo_doc = 96                          ' CUIT
nro_doc = "28136325"
nombre_cliente = "Federico Finki"
domicilio_cliente = "Lima"
tipo_responsable = 5                  ' consumidor final
referencia = "00000189"                       ' solo para NC / ND
    
ok = fiscal.AbrirComprobante(tipo_cbte, tipo_responsable, _
                             tipo_doc, nro_doc, _
                             nombre_cliente, domicilio_cliente, _ 
                             referencia)

Wscript.Echo "Abrir Comprobante = ", ok
    
' Imprimo un artículo:
codigo = "P0001"
ds = "nota de credito F B 00000189 prueba"
qty = 1.00
precio = 1.00
bonif = 0.00
alic_iva = 21.00
importe = 1.21
ok = fiscal.ImprimirItem(ds, qty, importe, alic_iva)
Wscript.Echo "ImprimirItem = ", ok

' Imprimir un pago (si es superior al total, se imprime el vuelto):
ok = fiscal.ImprimirPago("efectivo", importe)
Wscript.Echo "ImprimirPago = ", ok
    
' Finalizar el comprobante (imprime pie del comprobante, CF DGI, etc.) 
ok = fiscal.CerrarComprobante()
Wscript.Echo "CerrarComprobante = ", ok

If fiscal.Excepcion <> "" Then
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion: " + fiscal.Excepcion
End If

Wscript.Echo "Finalizado"
