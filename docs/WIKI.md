# Wiki del proyecto: Seguimiento de portafolio

## 1. Objetivo

Construir una aplicación que permita registrar, consultar y evaluar inversiones en renta variable y renta fija.

## 2. Activos

Renta variable:
- Bancolombia (acción local en COP).
- Amazon (AMZN, USD).
- The Coca-Cola Company (KO, USD).
- Nike (NKE, USD).

Renta fija:
- CDT.
- Bonos.
- TES.

Los activos de renta fija se registran con sus unidades nominales y precio/valor unitario. Para una implementación de valoración completa se deben ampliar los campos contractuales: tasa, modalidad, frecuencia de cupón, fecha de emisión, vencimiento, amortización y convención de días.

## 3. Flujo de uso

1. Abrir la aplicación.
2. Revisar los activos precargados.
3. Actualizar el precio o valoración del activo.
4. Registrar una compra.
5. Registrar ventas cuando corresponda.
6. Registrar dividendos o intereses cuando se reciban.
7. Revisar el resumen del portafolio.
8. Verificar la tasa USD/COP usada en la consolidación.

## 4. Cálculos

### Costo de compra

Cantidad × precio + comisión.

### Ingreso neto por venta

Cantidad × precio − comisión.

### Costo promedio ponderado

Costo total de las unidades disponibles / unidades disponibles.

### Resultado realizado

Ingreso neto por venta − costo promedio de las unidades vendidas.

### Resultado no realizado

Valor de mercado de las unidades actuales − costo de adquisición pendiente.

### Resultado total

Resultado realizado + resultado no realizado + dividendos + intereses.

### Rentabilidad acumulada simplificada

Resultado total / compras acumuladas × 100.

### XIRR

La TIR anualizada se estima encontrando la tasa que hace que el valor presente neto de los flujos fechados sea cero. Las compras son flujos negativos; ventas, dividendos e intereses son positivos; el valor actual de las posiciones se incorpora como flujo terminal positivo.

## 5. Condiciones contractuales de renta fija

La aplicación permite registrar para cada CDT, bono o TES:
- Tasa anual y tipo de tasa.
- Fecha de emisión o apertura.
- Fecha de vencimiento.
- Frecuencia de pago.
- Valor nominal o capital.
- Observaciones.

Estos datos quedan almacenados para documentar el contrato. La versión académica inicial no calcula todavía el precio teórico ni genera automáticamente el calendario de cupones.

## 6. Base de datos

SQLite contiene cuatro tablas:
- `assets`: datos de los activos.
- `transactions`: compras y ventas.
- `income_events`: dividendos e intereses.
- `price_history`: historial de precios ingresados o consultados.

## 7. Limitaciones conocidas

- La cotización de Bancolombia local se ingresa manualmente.
- La consulta de precios por yfinance puede fallar o estar retrasada.
- La tasa USD/COP se introduce manualmente.
- No se incorporan impuestos, retenciones, inflación ni valoración avanzada de bonos.
- La rentabilidad acumulada usa compras acumuladas como denominador y es una medida simplificada; no sustituye la XIRR ni la rentabilidad ponderada por tiempo.
- Para comparar correctamente instrumentos de renta fija se deben cargar sus términos contractuales reales.

## 8. Pruebas

Ejecutar desde la raíz del proyecto:

`python -m unittest discover -s tests -v`
