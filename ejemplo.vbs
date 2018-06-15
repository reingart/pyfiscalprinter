
' Ejemplo de Uso de Interface COM para imprimir en controladores fiscales
' homologados por AFIP en Argentina (Hasar, Epson y similares) utilizando
' intefaz PyFiscalPrinter: https://code.google.com/p/pyfiscalprinter/
' 2015 (C) Mariano Reingart <reingart@gmail.com>

' Registrar/iniciar python controlador.py --register (Windows)

Set fiscal = Wscript.CreateObject("PyFiscalPrinter")

MsgBox cstr(fiscal.Version), vbInformation + vbOKOnly, "Ver PyFiscalPrinter"

' En VB 5/6 clasico usar: Set fiscal = CreateObject("PyFiscalPrinter")

marca = "epson"            ' configurar "hasar" o "epson"
modelo = "TM-T900FA"       ' "tickeadoras", "epsonlx300+", "tm-220-af"
                           ' "615", "715v1", "715v2", "320"
puerto = "COM1"            ' "COM1", "COM2", etc.
equipo = ""                ' IP si no esta conectada a esta máquina

ok = fiscal.Conectar(marca, modelo, puerto, equipo)
    
' Analizar errores (si no se habilito lanzar excepciones)
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion: " + fiscal.Excepcion
End If

' Consultar el último número de comprobante impreso por el controlador:
' IMPORTANTE: en modo dummy solicita el número de comprobante por consola
tipo_cbte = 83
ult = fiscal.ConsultarUltNro(tipo_cbte)
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion Ult: " + fiscal.Excepcion
End If
MsgBox "Ultimo Nro de Cbte = " & ult

' Creo una factura de ejemplo:
tipo_cbte = 83                          ' Tique
tipo_doc = 96                          ' CUIT
nro_doc = "28136325"
nombre_cliente = "Federico Finki"
domicilio_cliente = "Lima"
tipo_responsable = 5                  ' consumidor final
referencia = "081-00001-00000027"                       ' solo para NC / ND
cbtes_asoc = "903-00001-00000001"
 
ok = fiscal.AbrirComprobante(tipo_cbte, tipo_responsable, _
                             tipo_doc, nro_doc, _
                             nombre_cliente, domicilio_cliente, _ 
                             referencia, cbtes_asoc )

If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion Abrir: " + fiscal.Excepcion
End If
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
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion Item: " + fiscal.Excepcion
End If
Wscript.Echo "ImprimirItem = ", ok

' Imprimir un pago (si es superior al total, se imprime el vuelto):
ok = fiscal.ImprimirPago("efectivo", importe)
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion Pago: " + fiscal.Excepcion
End If
Wscript.Echo "ImprimirPago = ", ok
    
' Finalizar el comprobante (imprime pie del comprobante, CF DGI, etc.) 
ok = fiscal.CerrarComprobante()
If fiscal.Excepcion <> "" Then 
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion Cerrar: " + fiscal.Excepcion
End If
Wscript.Echo "CerrarComprobante = ", ok

If fiscal.Excepcion <> "" Then
    MsgBox fiscal.Traceback, vbInformation + vbOKOnly, "Excepcion: " + fiscal.Excepcion
End If

Wscript.Echo "Finalizado"
