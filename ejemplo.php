<?php
# Ejemplo de Uso de Interface COM para imprimir en controladores fiscales
# homologados por AFIP en Argentina (Hasar, Epson y similares) utilizando
# intefaz PyFiscalPrinter: https://code.google.com/p/pyfiscalprinter/
# 2014 (C) Mariano Reingart <reingart@gmail.com>

# En windows habilitar COM en php.ini: extension=c:\PHP\ext\php_com_dotnet.dll

error_reporting(-1);

try {

	# Crear objeto interface con el componente del controlador fiscal:
    echo "creando interface ...";
	$ctrl = new COM('PyFiscalPrinter') or die("No se puede crear el objeto");
    echo "interface creada version {$ctrl->Version}\n";

    # habilitar excecpciones (capturarlas con un bloque try/except), ver abajo:
    $ctrl->LanzarExcepciones = true;

    # Iniciar conexión con el controlador fiscal:
    $marca = "epson";            // configurar "hasar" o "epson"
    $modelo = "epsonlx300+";     // "tickeadoras", "epsonlx300+", "tm-220-af"
                                 // "615", "715v1", "715v2", "320"
    $puerto = "dummy";           // "COM1", "COM2", etc.
    $equipo = "";                // IP si no esta conectada a esta máquina
    $ok = $ctrl->Conectar($marca, $modelo, $puerto, $equipo);
    
    # Analizar errores (si no se habilito lanzar excepciones)
    if (!$ok) {
        echo "Excepcion: {$ctrl->Excepcion}\n";
        echo "Traza: {$ctrl->Traceback}\n";
        exit(1);
    }

    # Consultar el último número de comprobante impreso por el controlador:
    $tipo_cbte = 83;
    $ult = $ctrl->ConsultarUltNro($tipo_cbte);
    echo "Ultimo Nro de Cbte {$ult}\n";    

    # Creo una factura de ejemplo:
    $tipo_cbte = 6;                         // factura B
    $tipo_doc = 80;                         // CUIT
    $nro_doc = "20267565393";
    $nombre_cliente = 'Mariano Reingart';
    $domicilio_cliente = 'Balcarce 50';
    $tipo_responsable = 5;                  // consumidor final
    $referencia = "";                       // solo para NC / ND
    
    $ok = $ctrl->AbrirComprobante($tipo_cbte, $tipo_responsable, 
                                  $tipo_doc, $nro_doc,
                                  $nombre_cliente, $domicilio_cliente, 
                                  $referencia);
    echo "Abrir Comprobante = {$ok}\n";    
    
    # Imprimo un artículo:
    $codigo = "P0001";
    $ds = "Descripcion del producto P0001";
    $qty = 1.00;
    $precio = 100.00;
    $bonif = 0.00;
    $alic_iva = 21.00;
    $importe = 121.00;
    $ok = $ctrl->ImprimirItem($ds, $qty, $importe, $alic_iva);
    echo "ImprimirItem = {$ok}\n";

    # Imprimir un pago (si es superior al total, se imprime el vuelto):
    $ok = $ctrl->ImprimirPago("efectivo", $importe);
    echo "ImprimirPago = {$ok}\n";
    
    # Finalizar el comprobante (imprime pie del comprobante, CF DGI, etc.) 
    $ok = $ctrl->CerrarComprobante();
    echo "CerrarComprobante = {$ok}\n";

} catch (Exception $e) {
	echo 'Excepción: ',  $e->getMessage(), "\n";
}

echo "Finalizado\n";
?>
