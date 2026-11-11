# Portafolio de inversión

Aplicación en Python + Streamlit + SQLite para llevar el control de un portafolio personal:
acciones, CDT, TES y bonos, dividendos y rentabilidad. Es una herramienta de seguimiento y
formación: **no ejecuta órdenes ni se conecta a tu cuenta de Trii** y no es asesoría financiera.

## Cómo ejecutarla en Windows

1. Abre la carpeta del proyecto (`C:\Users\Samar\OneDrive\Documentos\PORTAFOLIO_DE_INVERSION`) en VS Code.
2. Abre la terminal (menú Terminal > Nueva terminal) y escribe, una línea a la vez:

   ```
   py -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   python -m unittest discover -s tests
   streamlit run app.py
   ```
   (Si ya tenías el entorno `.venv`, solo necesitas `.\.venv\Scripts\activate`, `pip install -r requirements.txt` y `streamlit run app.py`.)
3. Se abre el navegador con la aplicación. Para cerrarla, presiona `Ctrl + C` en la terminal.

Si PowerShell no deja activar el entorno, ejecuta una vez
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a intentarlo.

## Tus datos están protegidos

* La base `portfolio_data.db` **nunca se borra ni se reemplaza**. No está en GitHub (está en `.gitignore`); vive solo en tu carpeta.
* La primera vez que abras esta versión, la app **hace una copia automática** en la carpeta `backups/` antes de actualizar la base. Después solo *agrega* columnas y tablas nuevas; no elimina nada.
* Puedes crear otra copia cuando quieras con el botón *Crear copia de seguridad ahora* del panel lateral.
* Consejo: la carpeta está en OneDrive. Cierra la app antes de que OneDrive sincronice grandes cambios y no abras la misma base desde dos computadores a la vez.

## Cómo se usa

**Registrar una compra** (pestaña *Compra y venta*): elige *COMPRA*. Si la empresa ya existe, selecciónala; si es nueva, elige *Empresa nueva* y llena nombre, símbolo, moneda y mercado: la empresa y la compra se guardan juntas. Ingresa fecha, cantidad y precio; la app estima la comisión. Si ya tienes el comprobante, marca *Ya tengo el comprobante* y escribe la comisión real.

**Registrar una venta**: elige *VENTA* y la acción (solo aparecen las que tienes). La app no deja vender más de lo que tenías en esa fecha.

**Registrar un dividendo** (pestaña *Dividendos*): elige la inversión, la fecha y el valor **bruto**; si hubo retención u otros costos, anótalos. Si dejas *Otros costos* en 0 y la acción es en COP, la app estima el costo de Trii (1 %, mínimo $200) y lo marca como estimado; corrígelo en *Historial* con tu comprobante. Si repites un pago idéntico, la app lo rechaza para no contarlo dos veces.

**Registrar un CDT, TES o bono** (pestañas *CDT* y *TES y bonos*): abre *Registrar…* y llena capital, tasa, modalidad, fechas y frecuencia de pago. Los intereses que vayas recibiendo se anotan en *Dividendos* (tipo INTERES). Al vencimiento usa *Registrar redención* con el total recibido; así se calcula la ganancia. Si registras el total en la redención, no lo repitas como interés.

## Precios y ganancias

* **Precio actual.** En *Consultar acciones* puedes consultar Yahoo Finance (`yfinance`) o escribir el precio que ves en Trii. Cada precio guarda **fuente y fecha**. Yahoo entrega el **último cierre diario**, que no es un precio en tiempo real. Muchos símbolos colombianos no existen en Yahoo: en ese caso usa el precio manual.
* **Precio faltante = Pendiente.** Nunca se toma como cero ni como pérdida: ese activo queda fuera del valor actual y de la rentabilidad, y se muestra un aviso.
* **Costo promedio ponderado.** El costo incluye la comisión de compra. Al vender, el costo de lo vendido es el costo promedio × cantidad.
* **Ganancia realizada** = (precio × cantidad − comisión de venta) − costo de lo vendido.
* **Ganancia no realizada** = (cantidad que conservas × precio actual) − costo de lo que conservas.
* **Resultado total** = realizada + no realizada + dividendos netos. Las comisiones ya están dentro del costo y de lo realizado, por eso no se restan otra vez (se muestran aparte solo como información).
* **Rentabilidad total** = resultado total ÷ total comprado (solo activos con precio conocido). La **TIR anualizada (XIRR)** usa las fechas reales de cada flujo y solo se calcula si todos los activos tienen precio y tasa de cambio.
* **USD/COP.** La tasa se guarda con fuente y fecha (consulta de mercado de Yahoo, o la TRM oficial que ingreses). Sin tasa, las acciones en dólares no se suman en pesos.

## Comisiones de Trii

Tarifas de referencia, revisadas el 9-nov-2026 en [trii.co/faq](https://trii.co/faq) y [trii.co/acciones-estados-unidos](https://trii.co/acciones-estados-unidos):

| Concepto | Estándar | Pro | Estado |
|---|---|---|---|
| Bolsa de Colombia | $12.500 + IVA (= $14.875) hasta $5.000.000; 0,25 % + IVA por encima | 0,125 % con mínimo $6.250 + IVA | Estándar **verificado**; Pro **NO verificado** (Trii no publica la tarifa Pro de acciones colombianas; es una estimación) |
| Bolsa de EE. UU. | 0,2 % | sin comisión | **Verificado** (la página no aclara si suma IVA: configurable) |
| Dividendos (acciones en COP) | 1 % del dividendo recibido, mínimo $200, más retención en la fuente si aplica | igual | **Verificado** el valor; no se sabe si lleva IVA (configurable) |

Todo es una **estimación configurable** (panel lateral): la comisión real es la de tu comprobante. Se corrige en *Historial*, tanto la de compras/ventas como la retención y costos de dividendos. Trii también hace jornadas sin comisión (por ejemplo, el "Día trii"); en esos casos corrige la comisión a 0 con el comprobante.

## ¿Se puede conectar con Trii?

No encontré una API pública y documentada de Trii (revisé trii.co/faq y búsquedas web el 9-nov-2026; no mencionan API ni acceso para desarrolladores). Por eso la aplicación **no simula ninguna conexión y nunca te pide contraseñas ni tokens**. La alternativa segura es la que ya incluye: precios desde Yahoo Finance cuando el símbolo existe, o ingreso manual con fuente y fecha, y comisiones corregibles con el comprobante. Si Trii publica una API oficial en el futuro, se puede agregar como una fuente más.

## Limitaciones

* Yahoo Finance no es tiempo real y puede no tener tus acciones colombianas. `yfinance` es una librería de terceros no afiliada a Yahoo; revisa sus términos de uso.
* La tasa de mercado de Yahoo no es la TRM oficial.
* Las operaciones en USD se convierten con la tasa actual, no con la del día de cada operación (afecta la TIR).
* CDT, TES y bonos se valoran a costo registrado. El interés estimado al vencimiento solo se calcula para tasas efectivas anuales con pago al vencimiento y es bruto de impuestos. No hay precio limpio/sucio, cupones ni intereses corridos.
* No calcula impuestos, retención en la fuente ni inflación.
* No hay opción de borrar o editar operaciones (para conservar el historial completo); solo se puede corregir la comisión y, en dividendos, la retención y los costos.
* La consulta en vivo a Yahoo Finance no pudo probarse en el entorno de desarrollo (red bloqueada); las pruebas simulan sus respuestas. Pruébala en tu computador.

## Pruebas

`python -m unittest discover -s tests -v` ejecuta las 73 pruebas de cálculos, comisiones, dividendos, formato, migración de la base antigua y apertura de la aplicación.

## Estructura

* `app.py`: interfaz Streamlit (tema oscuro en `.streamlit/config.toml`).
* `portfolio/database.py`: SQLite, copias de seguridad y migraciones que solo agregan.
* `portfolio/portfolio_service.py`: costo promedio, ganancias, resumen y renta fija.
* `portfolio/fees.py`: comisiones estimadas.
* `portfolio/market_data.py`: cotizaciones (yfinance) con fuente y fecha.
* `portfolio/formatting.py`: formato de pesos, dólares, cantidades y porcentajes.
* `tests/`: pruebas automáticas. `docs/`: wiki y diagramas.
