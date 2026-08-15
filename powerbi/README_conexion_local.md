# Conectar Power BI Desktop al stack local

El stack corre en esta misma máquina, así que Power BI se conecta a
`localhost`, sin necesidad de nube.

## 1. Datos → Obtener datos → Base de datos PostgreSQL

- **Servidor:** `localhost:5432`
- **Base de datos:** `cmms_dw`
- **Modo de conectividad de datos:**
  - `DirectQuery` → para el dashboard operativo (KPIs, OTs en Kanban) que necesita verse casi en tiempo real, igual que el dashboard de Fracttal visto en las capturas.
  - `Import` → para reportes históricos pesados (confiabilidad, calibraciones vencidas) que no necesitan refresco cada minuto.
- **Usuario:** `cmms_admin`
- **Contraseña:** `cmms_local_pw_change_me` (cámbiala en `docker-compose.yml` antes de ir a producción)

## 2. Tablas/vistas recomendadas para importar

Todas están en el esquema `mart` (ya vienen limpias y listas, no uses `staging` ni `core` directo en Power BI):

- `mart.dim_activo` (ya incluye sede y servicio clínico como columnas)
- `mart.dim_responsable`
- `mart.dim_tiempo`
- `mart.fact_orden_trabajo`
- `mart.fact_lectura_medidor`
- `mart.kpi_dashboard`

## 3. Relaciones sugeridas en el modelo de Power BI

```
dim_activo (codigo_activo) ──1:N── fact_orden_trabajo (activo_codigo)
dim_activo (codigo_activo) ──1:N── fact_lectura_medidor (activo_codigo)
dim_tiempo (fecha)          ──1:N── fact_orden_trabajo (fecha_programada)
```

> Nota: las relaciones se hacen por `codigo_activo` (texto, ej. `EQ-0001`),
> no por `activo_id` numérico — así se diseñó el modelo para simplificar
> el pipeline de carga (ver `sql/schema/02_core.sql`).

## 4. Visuales equivalentes al dashboard de Fracttal (para replicar lo visto en las capturas)

- Tarjetas KPI: `mart.kpi_dashboard` → OTs en Proceso / En Revisión / Finalizadas / Tareas con atraso
- Gráfico de dona: OTs por estado (`fact_orden_trabajo.estado`)
- Gráfico de barras: OTs por `tipo_equipo` (join con `dim_activo`)
- Línea de tiempo: `fact_lectura_medidor.valor` vs `fecha_lectura`, con línea de referencia en `valor_umbral_alerta`
- Tabla: activos con `calibracion_vencida = TRUE` (alerta de cumplimiento normativo — relevante para auditorías clínicas)

## 5. Cuando haya presupuesto de nube

Cambiar el **Servidor** de `localhost:5432` a la instancia gestionada
(ej. `<nombre>.postgres.database.azure.com:5432`) y publicar el reporte
al servicio Power BI para compartirlo sin depender de este equipo.
