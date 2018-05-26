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

"Servidor local HTTP JSONP para aplicaciones web con controladores fiscales"

__author__ = "Mariano Reingart <reingart@gmail.com>"
__copyright__ = "Copyright (C) 2014 Mariano Reingart"
__license__ = "GPL 3.0"
__version__ = "1.00a"

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import cgi
import time
import os

from controlador import ControladorFiscal

# ejemplo para http://localhost:8000 :

INDEX = """
<!doctype html>
<html>
<head>
<script src="http://localhost:8000/hola.js"></script>
<script type="text/javascript">
window.onload = function() {
    function ejecutar(url) {
        var s = document.createElement('script');
        s.type = "text/javascript";
        s.src = url;
        document.body.appendChild(s);
    }
    ejecutar("http://localhost:8000/Conectar.js?marca=epson&modelo=epsonlx300+&puerto=COM2&callback=alert");
    ejecutar("http://localhost:8000/ConsultarUltNro.js?tipo_cbte=6&callback=alert");
    ejecutar("http://localhost:8000/AbrirComprobante.js?tipo_cbte=6&callback=alert");
    ejecutar("http://localhost:8000/ImprimirItem.js?ds=Producto+Prueba&qty=1.00&importe=121.00&callback=alert");
    ejecutar("http://localhost:8000/CerrarComprobante.js?callback=alert");    
    alert("terminado!");
}
</script>
</head>
<body>
<h1>Prueba JSONP</h1>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith(("/", "/hola.js")):
            self.send_error(404, "File not found")
        else:
            if self.path == "/":
                # muestro la página de ejemplo
                content = INDEX
                content_type = "text/html"
            elif '?' in self.path:
                # analizo la URL, extrayendo las variables:
                path, tmp = self.path.split('?', 1)
                method, ext = os.path.splitext(path[1:])
                qs = cgi.parse_qs(tmp)
                # obtengo la función a llamar
                fn = getattr(self.server.controlador, method) 
                callback = qs['callback'].pop()
                kwargs = dict([(k, v[0]) for k, v in qs.items() if v])
                # ejecuto el método del controlador
                ret = fn(**kwargs)
                # reviso el valor devuelto (limpio si es excepción):
                ex = self.server.controlador.Excepcion
                if ex:
                    ex = ex.replace('"', "").replace("'", "").replace("\n", "")
                    if isinstance(ex, str):
                        ex = ex.decode("ascii", "replace")
                    # devuelvo JS que muestre la excepción:
                    content = """alert("%s");""" % (ex.encode("ascii", "replace"))
                else:
                    if ret is None:
                        ret = "OK"
                    # devuelvo JS que llame al callback en el navegador:
                    content = """%s(%s);""" % (callback, repr(ret))
                content_type = "application/javascript"
                print content
            else:
                # prueba simple:
                content_type = "application/javascript"
                content = """alert("hola mundo %s!");""" % time.time()
            # envío la respuesta (no cachear y compatibilidad con IE 8):
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("X-UA-Compatible", "IE=8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", 0)
            self.end_headers()
            self.wfile.write(content)

# levanto el servidor local:
server = HTTPServer(("localhost", 8000), Handler)
server.controlador = ControladorFiscal()
server.serve_forever()

