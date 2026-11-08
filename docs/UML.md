# Diagramas UML

Los diagramas se escriben en Mermaid. GitHub puede mostrar diagramas Mermaid en archivos Markdown.

## 1. Diagrama de clases

```mermaid
classDiagram
    class Asset {
        +int id
        +str name
        +str symbol
        +str asset_type
        +str currency
        +str market
        +float current_price
    }
    class Transaction {
        +int id
        +int asset_id
        +str operation
        +str date
        +float quantity
        +float price
        +float commission
    }
    class IncomeEvent {
        +int id
        +int asset_id
        +str event_type
        +str date
        +float amount
        +str description
    }
    class Database {
        +connect()
        +initialize()
        +get_assets()
        +add_transaction()
        +add_income()
        +update_price()
    }
    class MarketDataProvider {
        +fetch_yfinance_price(symbol)
        +today()
    }
    class PortfolioService {
        +positions()
        +xirr(flows)
        +summary(usd_cop)
    }
    Database --> Asset : stores
    Database --> Transaction : stores
    Database --> IncomeEvent : stores
    PortfolioService --> Database : queries
    MarketDataProvider ..> Database : price update
```

## 2. Diagrama de casos de uso

```mermaid
flowchart LR
    U[Usuario]
    A((Consultar portafolio))
    B((Registrar compra))
    C((Registrar venta))
    D((Registrar dividendo o interés))
    E((Actualizar precio))
    F((Consultar rentabilidad))
    G((Consultar distribución))
    U --> A
    U --> B
    U --> C
    U --> D
    U --> E
    U --> F
    U --> G
```

## 3. Flujo de compra

```mermaid
flowchart TD
    A([Inicio]) --> B[Seleccionar activo]
    B --> C[Ingresar fecha, cantidad y precio]
    C --> D[Ingresar comisión]
    D --> E{¿Datos válidos?}
    E -- No --> C
    E -- Sí --> F[Calcular costo total]
    F --> G[Guardar operación en SQLite]
    G --> H[Actualizar posiciones]
    H --> I[Mostrar confirmación]
    I --> J([Fin])
```

## Nota de mantenimiento

Si se modifican las clases o responsabilidades del código, actualizar este documento para que el UML siga coincidiendo con la implementación.
