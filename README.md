# CMMS Clínico — Demo local (ETL + Postgres + Airflow + Power BI)

Stack completo corriendo **100% en esta máquina** (actúa como servidor).
No depende de ningún servicio cloud. Cuando la clínica apruebe presupuesto
de nube, solo se cambian 2-3 variables de entorno — el resto del proyecto
no se toca (ver `docker-compose.yml`, comentario superior).

Todos los datos son **sintéticos** (infraestructura crítica simulada:
generadores eléctricos, chillers de climatización, bombas, transformadores,
sistema de oxígeno medicinal, etc. — NO equipamiento biomédico de
atención al paciente) porque la clínica
todavía no tiene licencia de Fracttal ni acceso a su API. El conector
real (`connectors/fracttal_client.py`) ya está escrito y listo — el día
que haya credenciales, se cambia `CMMS_USE_DEMO_DATA=false` y se cargan
`FRACTTAL_CLIENT_ID` / `FRACTTAL_CLIENT_SECRET` como Airflow Connection.

## Requisitos en esta máquina
- Docker + Docker Compose
- (Opcional) Power BI Desktop, si Windows / vía Wine, o Power BI Service si más adelante hay nube

## Publicar la webapp online (gratis)

`render.yaml` en la raíz del repo es un Blueprint de [Render](https://render.com)
que despliega la webapp + una base Postgres gratuita, con las credenciales
conectadas automáticamente (sin copiar/pegar connection strings):

1. Sube este repo a GitHub.
2. En Render: **New → Blueprint** → selecciona el repo → **Apply**.
3. Al terminar, la URL pública queda en el dashboard del servicio `cmms-webapp`.

El primer arranque corre `scripts/bootstrap_schema.py` (aplica `sql/schema/*.sql`
— seguro de repetir, todo usa `IF NOT EXISTS`) y `scripts/seed_demo_users.py`
(crea admin/supervisor/tecnico/operador) automáticamente — no hace falta
tocar la base a mano. Solo Airflow y el pipeline ETL **no** se despliegan
ahí (se quedan corriendo localmente); si quieres los datos demo ya
cargados en la base de Render, hay que migrarlos una vez con `pg_dump`/`psql`
desde el Postgres local.

**Nota:** el plan free de Render Postgres expira a los 90 días — hay que
recrear la base (o subir de plan) después de esa fecha.

## Arranque

```bash
cd cmms-demo
docker compose up -d
```

Esto levanta:
| Servicio | URL local | Credenciales |
|---|---|---|
| Airflow UI | http://localhost:8080 | admin / admin |
| Adminer (explorador DB) | http://localhost:8081 | Sistema: PostgreSQL, Servidor: `postgres_dw`, Usuario: `cmms_admin`, Pass: `cmms_local_pw_change_me`, BD: `cmms_dw` |
| Postgres DW (para Power BI) | `localhost:5432` | mismo usuario/pass, BD `cmms_dw` |
| MySQL demo (ERP externo simulado) | `localhost:3307` | Usuario: `erp_demo`, Pass: `erp_demo_pw`, BD: `erp_demo` |
| Mock JSON-RPC 2.0 | http://localhost:5099 | sin auth — `POST /` con body `{"jsonrpc":"2.0","method":"tareas.list","id":1}` |

Los últimos 2 son parte del **motor ETL genérico** (conectores SQL/API/archivo
más allá de Fracttal) — ver [`docs/ARQUITECTURA_ETL.md`](docs/ARQUITECTURA_ETL.md)
para el detalle completo (catálogo de conectores, 70 operadores de
transformación disponibles, sistema de eventos, cómo agregar una fuente
nueva sin escribir código).

La primera vez, `postgres_dw` ejecuta automáticamente todo lo que hay en
`sql/schema/*.sql` (staging + core + mart) al inicializarse.

## Cargar datos demo

Los DAGs `cmms_activos`, `cmms_ordenes_trabajo`, `cmms_tareas` y
`cmms_medidores` corren automáticamente según su schedule (ver
`MODULE_SCHEDULES` en `airflow/dags/dag_cmms_pipeline.py`). Para forzar
una corrida manual inmediata y ver el pipeline completo funcionando,
**respeta este orden** (hay dependencias por foreign key):

1. Entra a http://localhost:8080
2. Activa (unpause) los 6 DAGs `cmms_*`
3. Dispara `cmms_activos` primero (▶) — todo lo demás referencia el activo por su código
4. Luego `cmms_ordenes_trabajo`, `cmms_tareas`, `cmms_almacenes`, `cmms_recursos_humanos` (en cualquier orden entre ellos)
5. Luego `cmms_medidores` (ya trae catálogo → lecturas encadenado internamente)
6. Por último `cmms_repuestos_usados` — necesita que OTs Y almacenes ya estén cargados (FK)

> Validado localmente: el pipeline completo (5 módulos, ~560 registros)
> corre sin errores end-to-end contra Postgres 16 antes de entregarte
> este proyecto.

Verifica en Adminer (`localhost:8081`) que `core.activo` y
`core.orden_trabajo` tengan filas.

## Conectar Power BI (local)

Ver `powerbi/README_conexion_local.md`.

## Órdenes de trabajo transaccionales

El Kanban ya no es solo de lectura. Desde ahí (o desde `/ot/nueva`) se
puede:

- **Crear una OT** — queda en estado `Pendiente`.
- **Avanzar de estado** — botones en cada tarjeta según el estado
  actual (`Iniciar`, `Enviar a revisión`, `Rechazar`).
- **Finalizar con repuestos** — al finalizar, se pueden registrar los
  repuestos usados. Esto descuenta el stock del almacén **en la misma
  transacción**: si el stock no alcanza o cualquier paso falla, se
  revierte todo (la OT no queda "finalizada a medias" con el stock
  descontado, ni viceversa).
- **Ver historial** — cada cambio de estado queda auditado: quién,
  cuándo, de qué estado a qué estado (`core.orden_trabajo_historial`).

**Máquina de estados** (`webapp/transacciones.py`, `TRANSICIONES_VALIDAS`):
```
Pendiente → En Proceso → En Revisión → Finalizada
    ↓            ↓              ↓
Cancelada    Pendiente      En Proceso   (retrocesos permitidos)
```
Saltos inválidos (ej. `Pendiente` directo a `Finalizada`) se rechazan
con un error explícito, no se corrigen "silenciosamente".

**Por qué estas rutas usan sesión y no la API key:** para saber *quién*
hizo cada cambio (columna `usuario_id` en el historial) hace falta
identidad de persona, no de sistema — una API key identifica una
integración, no a Juan Pérez. Si más adelante se necesita crear OTs
desde un sistema externo, se puede agregar un endpoint de API que
reciba explícitamente el usuario en el payload.

**Probado en vivo antes de la entrega** (no solo con mocks): creé una
OT real, la avancé por los 3 estados, intenté una transición inválida
(rechazada correctamente), la finalicé con repuestos — verifiqué con
SQL directo que el stock bajó exactamente lo esperado y el historial
quedó completo. También probé el camino de error: pedir más repuesto
del que hay en stock revierte todo (la OT no avanza).

## Autenticación y roles

4 roles: **ADMIN** (todo + gestión de usuarios), **SUPERVISOR** (dashboard
+ gestión, sin admin), **TECNICO** (kanban, vista árbol, activos — sin
dashboard), **OPERADOR** (pensado para cuando se agregue escritura desde
el piso, ej. "marcar tarea realizada").

**Decisión de diseño explícita:** `/panel/hoy` y `/activo/<codigo>`
quedan **sin login** — son el flujo físico real (QR pegado en el equipo,
pantalla de kiosco en el cuarto de máquinas). Pedir login ahí rompe ese
flujo. Todo lo demás (dashboard, kanban, vista árbol, listado de
activos, administración) sí exige sesión iniciada.

**Usuarios demo** (se crean solos al levantar `docker compose up`, vía
`scripts/seed_demo_users.py` — **desactivar antes de producción**):

| Usuario | Contraseña | Rol |
|---|---|---|
| admin | admin123 | ADMIN |
| supervisor | super123 | SUPERVISOR |
| tecnico | tecnico123 | TECNICO |
| operador | operador123 | OPERADOR |

**Gestión de usuarios reales** (por línea de comandos — más seguro que
un formulario web para esto):
```bash
# Desde el host, contra el puerto expuesto por docker compose:
python3 scripts/manage_users.py create --username jperez --nombre "Juan Pérez" --rol TECNICO
python3 scripts/manage_users.py list
python3 scripts/manage_users.py deactivate --username jperez
python3 scripts/manage_users.py reset-password --username jperez

# O dentro del contenedor (mismo efecto, sin instalar deps en el host):
docker compose exec webapp python scripts/manage_users.py list
```

**Antes de usar esto con la clínica real:**
1. `python3 scripts/manage_users.py deactivate --username admin` (y los otros 3 demo)
2. Crear las cuentas reales con `manage_users.py create`
3. Cambiar `CMMS_SECRET_KEY` y `CMMS_API_KEY` en `docker-compose.yml` a
   valores generados (ej. `python3 -c "import secrets; print(secrets.token_hex(32))"`)

## Infraestructura robusta — qué se endureció

Antes de construir una interfaz más rica encima, se cerraron estos huecos:

- **Capa de datos separada de la presentación** (`webapp/queries.py`): HTML
  y API consumen exactamente las mismas funciones — ya no hay 2 fuentes
  de verdad que puedan desincronizarse.
- **API REST en JSON** (`webapp/api.py`), protegida por header
  `X-API-Key` (variable `CMMS_API_KEY`, default `cmms-local-dev-key` —
  **cambiar antes de producción**). Endpoints: `/api/dashboard`,
  `/api/vista-arbol`, `/api/kanban`, `/api/panel-hoy`, `/api/activos`
  (con filtros `?sede=&servicio=&criticidad=`), `/api/activos/<codigo>`.
  Las páginas HTML NO requieren la key (deben abrirse sin fricción desde
  el celular al escanear un QR).
- **Pool de conexiones a Postgres** (`webapp/db.py`) en vez de abrir/cerrar
  una conexión TCP por request.
- **Manejo de errores real**: página/JSON de error legible en 404/500/503
  (antes: traza cruda de Python). Ver `webapp/templates/error.html`.
- **Logging estructurado** de cada request (método, ruta, status, tiempo)
  y alerta automática si una consulta tarda más de 500ms.
- **`/health`** — endpoint de salud (revisa conexión real a Postgres),
  usado por el `healthcheck` de Docker Compose para reiniciar el
  contenedor si se cae.
- **`restart: unless-stopped`** en todos los servicios — si la máquina se
  reinicia o un contenedor falla, el stack vuelve solo.
- **Tipos JSON correctos en la API**: `Decimal` de Postgres se convierte a
  número real (antes salía como string), fechas en ISO 8601.
- **61 tests automatizados** (`webapp/tests/`, `transform/tests/`) que
  corren sin necesitar Postgres levantado (usan mocks) — se pueden correr
  en cualquier máquina o en CI:
  ```bash
  cd webapp && python3 -m pytest tests/ -v
  cd .. && python3 -m pytest transform/tests/ -v
  ```
  Estos tests ya encontraron y corrigieron **4 bugs reales** durante el
  desarrollo:
  1. Un operador `map_lookup` que se rompía con mapeos de 1 sola clave.
  2. Un caso de aislamiento de tests que dependía silenciosamente de una
     base de datos real corriendo (el mock no aplicaba por cómo Python
     importa nombres con `from X import Y`).
  3. `db.query()` reventaba con `UPDATE`/`INSERT` (intentaba `fetchall()`
     sobre sentencias que no devuelven filas).
  4. Las conexiones del pool nunca hacían `commit()` — cualquier
     escritura (ej. guardar el último login) se perdía silenciosamente.
     Se corrigió agregando `db.execute()`, separado de `db.query()`.

## Todos los módulos implementados

| Módulo | DAG | Tabla core | Frecuencia |
|---|---|---|---|
| Activos | `cmms_activos` | `core.activo` | Diaria |
| Órdenes de Trabajo | `cmms_ordenes_trabajo` | `core.orden_trabajo` | Cada 2h |
| Tareas | `cmms_tareas` | `core.tarea` | Cada 2h |
| Medidores + Lecturas | `cmms_medidores` (2 tareas encadenadas) | `core.medidor`, `core.lectura_medidor` | Cada 30 min |
| Almacenes / Repuestos | `cmms_almacenes` | `core.repuesto_almacen` | Diaria |
| Recursos Humanos | `cmms_recursos_humanos` | `core.responsable` | Diaria |
| Repuestos usados por OT | `cmms_repuestos_usados` | `core.ot_repuesto` | Cada 3h (después de OTs+Almacenes) |

Todos probados end-to-end contra Postgres 16 antes de la entrega: 8
módulos, ~750 registros, incluyendo eventos disparados (OTs correctivas
críticas y alertas de stock bajo de repuestos).

## App de escaneo QR + tablero de kiosco

Además del pipeline ETL, el proyecto incluye una app web liviana
(`webapp/`) pensada para el flujo físico real: un operador o inspector
se acerca a un equipo (ej. Chiller AAON en azotea piso 13), escanea el
QR pegado en el equipo, y cae directo en la ficha del activo.

**Levantar la app** (ya viene en `docker compose up -d`, servicio `webapp`):
- http://localhost:5090/dashboard — panel general: KPIs, OTs por tipo,
  activos por criticidad/área, inspecciones vencidas, stock bajo
- http://localhost:5090/vista-arbol — jerarquía Institución → Sede →
  Área técnica → Activo, igual que la vista árbol de un CMMS
- http://localhost:5090/kanban — tablero Kanban de OTs (Pendiente / En
  Proceso / En Revisión / Finalizada)
- http://localhost:5090/panel/hoy — tablero de kiosco: OTs y tareas
  programadas para HOY, pensado para mostrarse en una pantalla o
  tablet en el cuarto de máquinas
- http://localhost:5090/activos — listado simple de activos (acceso sin QR)
- http://localhost:5090/activo/EQ-0001 — ficha de un activo: uso
  estimado, historial de OTs, estado "apto"/"en atención", repuestos
  usados, últimas lecturas de sensor — **esto es lo que ve un operador
  al escanear el QR del equipo**

Todas las vistas se navegan desde el menú superior. Todo corre 100%
local (sin CDN externo — hasta Chart.js está empaquetado en
`webapp/static/`, no depende de internet).

**Generar los códigos QR físicos:**
```bash
# IMPORTANTE: usa la IP de esta máquina en la red de la clínica, no
# "localhost" — si no, el QR no funcionará al escanearlo desde un celular
QR_BASE_URL=http://<IP-de-esta-máquina>:5090 \
CMMS_DW_HOST=localhost \
python3 scripts/generate_qr_codes.py
```
Esto genera un PNG por activo en `qr_codes/` + una hoja imprimible
`qr_codes/index.html` (ábrela en el navegador y usa Imprimir → PDF, o
imprime directo, para pegar las etiquetas en cada equipo).

> Validado en esta sesión: 120 QRs generados y decodificados
> correctamente — cada uno apunta a `/activo/<código>` y muestra la
> información real cargada por el pipeline.



```
cmms-demo/
  docker-compose.yml          # todo el stack local
  sql/schema/                 # DDL: staging -> core -> mart (se auto-ejecuta)
  connectors/
    fracttal_client.py        # cliente REST/OAuth2 REAL (listo para prod)
    demo_data_generator.py    # misma interfaz, datos sintéticos clínicos
  transform/
    json_logic_engine.py      # motor de reglas + operadores custom
    postgres_loader.py        # valida (JSON Schema) + transforma + upsert
    config/*.json             # 1 archivo de mapeo por módulo
  airflow/dags/
    dag_cmms_pipeline.py      # 1 plantilla -> genera 1 DAG por módulo
  powerbi/
    README_conexion_local.md
```

## Próximos módulos a agregar (mismo patrón)
Para agregar Medidores/Lecturas, Almacenes o RRHH: solo hace falta
1) un archivo `transform/config/<modulo>.json` nuevo, y
2) agregar la entrada correspondiente en `MODULE_SOURCE_METHOD` /
`MODULE_SCHEDULES` del DAG factory. No se toca el resto del pipeline.

## Planos de la clínica (roadmap)

Ya dejé la base de datos lista para esto: `core.activo` tiene 3 columnas
nullable — `plano_referencia`, `plano_pos_x`, `plano_pos_y` — pensadas
para guardar en qué imagen de plano está cada activo y su posición (%
x/y) sobre esa imagen. Hoy están vacías porque no tengo los planos
todavía. Cuando los tengas:

1. Sube las imágenes de los planos (por piso/sede) a `webapp/static/planos/`
2. Ubica cada activo sobre el plano (una pasada manual de datos, o un
   pequeño editor visual — se puede construir sobre esta misma webapp)
3. Con `plano_referencia` + `plano_pos_x/y` llenos, se agrega una vista
   `/planos/<sede>` que dibuja el plano de fondo y un pin clickeable por
   activo (lleva a `/activo/<código>`) — mismo patrón que ya usa
   `vista_arbol.html` y `kanban.html`, solo cambia la presentación visual

No lo construí ahora porque no tiene sentido diseñar la interacción
(zoom, capas por piso, etc.) sin ver los planos reales primero — dime
cuando los tengas y lo armamos sobre datos reales, no inventados.

## Solución de problemas (troubleshooting)

**`ModuleNotFoundError: No module named 'transform'` en los logs de un DAG de
Airflow** — el contenedor de Airflow no tiene `/opt/airflow` en su
`PYTHONPATH`, así que no encuentra los paquetes `transform/` y
`connectors/` aunque estén montados ahí. Ya está corregido en este
`docker-compose.yml` (variable `PYTHONPATH: /opt/airflow` en
`x-airflow-common`). Si ves este error en una copia vieja del proyecto,
agrega esa línea al bloque de environment de `x-airflow-common` y
recrea los contenedores de Airflow:
```bash
docker compose up -d --force-recreate airflow-scheduler airflow-webserver
```

**El Dashboard muestra todo en cero pero Airflow tiene corridas
verdes** — casi siempre significa que hubo un `docker compose down -v`
en algún momento (borra los datos) después de esa corrida exitosa, y
las corridas más recientes están fallando (revisa si hay círculos
rojos en Airflow, y el log de la más reciente). Verificar directo en la
base: `docker compose exec postgres_dw psql -U cmms_admin -d cmms_dw -c
"select count(*) from core.activo;"`.

## Camino a producción / nube (cuando haya presupuesto)
1. Confirmar plan de Fracttal con "Integration API" habilitado.
2. Probar 1 endpoint real con Postman antes de tocar código.
3. Cargar credenciales reales como Airflow Connection `fracttal_api`.
4. Cambiar `CMMS_USE_DEMO_DATA=false` en `docker-compose.yml`.
5. Migrar `postgres_dw` a una instancia gestionada (ej. Azure Database
   for PostgreSQL) cambiando solo `CMMS_DW_HOST`.
6. Publicar dataset de Power BI al servicio Power BI (Pro/PPU) para
   compartirlo con la clínica sin depender de este equipo local.
