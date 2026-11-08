# Seguimiento de portafolio de inversión

Aplicación académica desarrollada en Python y Streamlit para registrar operaciones de compra y venta, ingresos por dividendos e intereses, actualizar precios y consultar el desempeño de un portafolio con activos de renta fija y renta variable.

## Empresas incluidas

- Bancolombia: acción local en Colombia. Su precio se ingresa manualmente a partir de una fuente de mercado verificable.
- Amazon: AMZN.
- The Coca-Cola Company: KO.
- Nike: NKE.

También se incluyen instrumentos de ejemplo para CDT, bonos y TES. Sus condiciones deben ser ingresadas por el usuario a partir de documentos o fuentes verificables.

## Funcionalidades

- Registro de activos.
- Registro de compras y ventas con fecha, cantidad, precio y comisión.
- Registro de dividendos e intereses.
- Actualización manual de precios y consulta de último cierre para AMZN, KO y NKE mediante yfinance.
- Conversión de posiciones en USD a COP mediante una tasa USD/COP ingresada por el usuario.
- Cálculo de costo de posición usando costo promedio ponderado.
- Resultado realizado y no realizado.
- Rentabilidad acumulada simplificada.
- TIR anualizada (XIRR) basada en flujos fechados.
- Distribución entre renta fija y renta variable.

## Requisitos

Python 3.10 o superior recomendado.

## Instalación en VS Code

1. Descarga o clona el repositorio.
2. Abre la carpeta `seguimiento-portafolio` en VS Code.
3. Abre la terminal integrada.
4. Crea un entorno virtual:

   Windows:
   `py -m venv .venv`
   `.\.venv\Scripts\activate`

   macOS/Linux:
   `python3 -m venv .venv`
   `source .venv/bin/activate`

5. Instala dependencias:

   `pip install -r requirements.txt`

6. Ejecuta las pruebas:

   `python -m unittest discover -s tests -v`

7. Ejecuta la aplicación:

   `streamlit run app.py`

La base de datos SQLite se crea automáticamente en la primera ejecución.

## Criterios financieros y supuestos

- La moneda consolidada de presentación es COP.
- Los activos en USD se convierten usando la tasa USD/COP que el usuario introduce en la barra lateral. El valor inicial de 4.000 COP/USD es solo un ejemplo, no una cotización vigente.
- Las comisiones se registran en la moneda del activo.
- El costo de adquisición incluye la comisión de compra.
- Las ventas descuentan la comisión y reconocen el resultado realizado con costo promedio ponderado.
- El resultado no realizado compara el valor actual con el costo de las unidades que siguen en cartera.
- Dividendos e intereses son ingresos. Una devolución de capital no debe registrarse como interés: debe reflejarse como reducción de la posición.
- La rentabilidad acumulada del tablero es una medida simplificada: (resultado realizado + resultado no realizado + ingresos) / compras acumuladas. Para aportes y retiros complejos, debe interpretarse junto con la XIRR.
- La XIRR estima una tasa anualizada con fechas reales de compras, ventas, ingresos y valor actual. Puede no existir una solución única o válida; en ese caso muestra N/D.
- La aplicación no calcula impuestos, retenciones, inflación, intereses corridos, precio limpio/sucio de bonos ni convenciones avanzadas de valoración de renta fija.

## Fuentes de datos

- Bancolombia – Relación con inversionistas: https://www.grupobancolombia.com/relacion-inversionistas
- Valores Bancolombia – Acciones: https://valores.bancolombia.com/productos-servicios/acciones
- Bancolombia – Consulta del precio de acciones: https://www.bancolombia.com/centro-de-ayuda/preguntas-frecuentes/consultar-precio-acciones-en-bancolombia
- SEC EDGAR: https://www.sec.gov/edgar/search/
- Yahoo Finance: https://finance.yahoo.com/
- BVC: https://www.bvc.com.co/
- Superintendencia Financiera: https://www.superfinanciera.gov.co/
- Banco de la República: https://www.banrep.gov.co/

`yfinance` es una biblioteca de terceros no afiliada ni respaldada por Yahoo. Está destinada a investigación y educación; revisa los términos de uso de Yahoo antes de utilizar sus datos.

## Estructura

- `app.py`: interfaz Streamlit.
- `portfolio/`: modelos, base de datos, proveedor de precios y reglas de negocio.
- `tests/`: pruebas automatizadas.
- `docs/`: wiki y diagramas UML.

## Alcance

Proyecto educativo. No ejecuta órdenes bursátiles, no se conecta a cuentas de bróker y no constituye asesoría financiera.


## Uso de la aplicación

- En **Resumen** ves valor actual, compras acumuladas, resultados, ingresos y distribución.
- En **Acciones** puedes actualizar AMZN, KO y NKE desde Yahoo Finance; Bancolombia local se ingresa manualmente.
- En **Comprar / vender** registras cada operación. La comisión se calcula automáticamente con el porcentaje editable en la barra lateral.
- En **CDT, bonos y TES** guardas tasa, modalidad, fechas, frecuencia y capital nominal.
- En **Dividendos e intereses** registras los pagos efectivamente recibidos.
- En **Rentabilidad y gráficos** consultas resultados por activo e historial de precios.
- En **Historial** revisas todas las operaciones y actualizaciones.

Los porcentajes de comisión que aparecen inicialmente (0,50% para acciones y 0% para instrumentos de renta fija) son valores ilustrativos editables, no tarifas oficiales. Configúralos según tu intermediario.

Para que una operación no se mezcle con la cotización actual, el precio de compra o venta queda guardado en su propio registro. Actualizar el precio de mercado no modifica las operaciones anteriores.


## Interfaz PORTAFOLIO DE INVERSIÓN

La aplicación incluye panel de resumen, consulta y actualización de acciones, registro de compras y ventas, CDT, TES y bonos, dividendos e intereses, rentabilidad y rentabilidad efectiva anual (XIRR), gráficos e historial.

Las comisiones por empresa se configuran en el panel lateral y quedan guardadas en SQLite. Los valores iniciales son ilustrativos, no tarifas oficiales.

Los precios actuales se conservan hasta que el usuario los actualiza. Las operaciones mantienen el precio histórico con el que fueron registradas. Los precios de acciones estadounidenses pueden consultarse con yfinance; las cotizaciones locales se ingresan manualmente.

Para CDT/TES/bonos se guardan las condiciones contractuales y el capital invertido. La app no calcula automáticamente precios de mercado, cupones futuros, impuestos, retenciones ni intereses corridos.
