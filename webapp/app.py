"""
App web -- sirve la interfaz completa del CMMS:

- /dashboard, /vista-arbol, /kanban, /activos      (requieren login)
- /panel/hoy, /activo/<codigo>                     (publicas -- flujo QR/kiosco)
- /admin/usuarios                                   (solo ADMIN)
- /api/*  (API REST en JSON, ver api.py -- para consumir desde una futura
  interfaz mas rica, apps moviles, o integraciones externas)

Corre contra el mismo Postgres (`cmms_dw`) que ya carga el pipeline ETL.
No requiere Airflow para funcionar, solo que el schema `mart`/`core` ya
tenga datos cargados.
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from flask import Flask, render_template, abort, redirect, url_for, request, jsonify, flash, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from psycopg2.extras import Json

from db import health_check, DatabaseError, execute, query, query_one
from queries import (
    get_dashboard_data, get_vista_arbol_data, get_kanban_data,
    get_panel_hoy_data, get_activos_list, get_activo_detalle, get_tareas_list,
    get_calendario_eventos, mover_evento_calendario, get_tareas_pendientes_kanban, NotFoundError,
)
from transacciones import (
    crear_orden_trabajo, cambiar_estado_ot, finalizar_ot, get_historial_ot,
    get_checklist_para_activo, get_checklist_respuestas_ot,
    InvalidTransitionError, BusinessRuleError, TRANSICIONES_VALIDAS,
)
from auditoria import registrar_evento, get_eventos, get_acciones_distintas
from auth import login_manager, authenticate, role_required
from api import api_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("cmms.app")

app = Flask(__name__)
app.secret_key = os.environ.get("CMMS_SECRET_KEY", "dev-secret-key-CHANGE-EN-PRODUCCION")
app.register_blueprint(api_bp, url_prefix="/api")
login_manager.init_app(app)


# JSON con fechas en ISO 8601 (estandar de facto para APIs REST) en vez
# del RFC 822 que usa Flask por defecto -- mas facil de consumir desde
# cualquier frontend (JS Date(), etc.)
from flask.json.provider import DefaultJSONProvider
import datetime as _dt


class ISODateJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, (_dt.date, _dt.datetime)):
            return obj.isoformat()
        return DefaultJSONProvider.default(obj)


app.json = ISODateJSONProvider(app)


# ---------------------------------------------------------------------
# Usuario actual disponible en TODOS los templates (nav bar, etc.)
# ---------------------------------------------------------------------
@app.context_processor
def inject_user():
    return {"current_user": current_user}


# ---------------------------------------------------------------------
# Observabilidad basica: log de cada request + healthcheck para Docker
# ---------------------------------------------------------------------
@app.before_request
def _start_timer():
    request._t0 = time.monotonic()


@app.after_request
def _log_request(response):
    elapsed = (time.monotonic() - getattr(request, "_t0", time.monotonic())) * 1000
    logger.info("%s %s -> %s (%.1fms)", request.method, request.path, response.status_code, elapsed)
    return response


@app.route("/health")
def health():
    ok = health_check()
    return jsonify({"status": "ok" if ok else "error", "db": "ok" if ok else "unreachable"}), (200 if ok else 503)


# ---------------------------------------------------------------------
# Manejo de errores -- paginas legibles en vez de trazas crudas
# ---------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not_found", "message": "Recurso no encontrado."}), 404
    return render_template("error.html", code=404, message="No encontramos esa pagina o ese activo."), 404


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "forbidden", "message": "Tu rol no tiene acceso a esto."}), 403
    return render_template("error.html", code=403, message="Tu rol no tiene acceso a esta seccion."), 403


@app.errorhandler(NotFoundError)
def not_found_domain(e):
    return not_found(e)


@app.errorhandler(DatabaseError)
def db_error(e):
    logger.error("DatabaseError: %s", e)
    if request.path.startswith("/api/"):
        return jsonify({"error": "database_error", "message": str(e)}), 503
    return render_template("error.html", code=503, message="No se pudo conectar a la base de datos. Intenta de nuevo en unos segundos."), 503


@app.errorhandler(500)
def server_error(e):
    logger.exception("Error 500")
    if request.path.startswith("/api/"):
        return jsonify({"error": "server_error", "message": "Error interno."}), 500
    return render_template("error.html", code=500, message="Ocurrio un error inesperado."), 500


# ---------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "")
        user = authenticate(username, request.form.get("password", ""))
        if user:
            login_user(user)
            execute("UPDATE core.usuario SET ultimo_login = now() WHERE usuario_id = %s", (user.id,))
            registrar_evento(usuario_id=int(user.id), accion="LOGIN", entidad_tipo="usuario", entidad_id=user.username,
                              ip_address=request.remote_addr)
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        registrar_evento(usuario_id=None, accion="LOGIN_FALLIDO", entidad_tipo="usuario", entidad_id=username,
                          ip_address=request.remote_addr)
        flash("Usuario o contrasena incorrectos.", "error")
    show_hint = os.environ.get("CMMS_SHOW_DEMO_LOGIN_HINT", "true").lower() == "true"
    return render_template("login.html", show_demo_hint=show_hint)


@app.route("/logout")
@login_required
def logout():
    registrar_evento(usuario_id=int(current_user.id), accion="LOGOUT", entidad_tipo="usuario", entidad_id=current_user.username,
                      ip_address=request.remote_addr)
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Paginas HTML -- gestion (requieren login)
# ---------------------------------------------------------------------
@app.route("/")
def raiz():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@role_required("ADMIN", "SUPERVISOR")
def dashboard():
    return render_template("dashboard.html", **get_dashboard_data())


@app.route("/vista-arbol")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def vista_arbol():
    return render_template("vista_arbol.html", arbol=get_vista_arbol_data())


@app.route("/kanban")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def kanban():
    return render_template("kanban.html", columnas=get_kanban_data(), tareas_pendientes=get_tareas_pendientes_kanban())


# ---------------------------------------------------------------------
# Órdenes de trabajo — operaciones TRANSACCIONALES (crear, avanzar,
# finalizar con repuestos). Autenticadas por SESIÓN (no API key) porque
# necesitamos saber qué usuario hizo cada cambio para el historial de
# auditoría — una API key identifica un sistema, no una persona.
# ---------------------------------------------------------------------
@app.route("/ot/nueva", methods=["GET", "POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def ot_nueva():
    if request.method == "POST":
        try:
            resultado = crear_orden_trabajo(
                activo_codigo=request.form["activo_codigo"],
                tipo_ot=request.form["tipo_ot"],
                descripcion_tarea=request.form["descripcion_tarea"],
                prioridad=request.form["prioridad"],
                fecha_programada=request.form["fecha_programada"],
                responsable_nombre=request.form.get("responsable_nombre") or None,
                clasificacion_1=request.form.get("clasificacion_1") or None,
                usuario_id=int(current_user.id), ip_address=request.remote_addr,
            )
            flash(f"OT {resultado['ot_id']} creada correctamente.", "info")
            return redirect(url_for("kanban"))
        except BusinessRuleError as e:
            flash(str(e), "error")

    activos = get_activos_list()
    return render_template(
        "ot_nueva.html", activos=activos,
        tipos_ot=["CORRECTIVO", "PREVENTIVO", "OVERHAUL", "CALIBRACION"],
        prioridades=["Muy Alta", "Alta", "Media", "Baja"],
        activo_preseleccionado=request.args.get("activo"),
    )


@app.route("/ot/<ot_id>/avanzar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def ot_avanzar(ot_id):
    nuevo_estado = request.form.get("nuevo_estado", "")
    try:
        cambiar_estado_ot(
            ot_id=ot_id, nuevo_estado=nuevo_estado, usuario_id=int(current_user.id),
            comentario=request.form.get("comentario") or None, ip_address=request.remote_addr,
        )
        flash(f"{ot_id} → {nuevo_estado}", "info")
    except (InvalidTransitionError, BusinessRuleError) as e:
        flash(str(e), "error")
    return redirect(request.form.get("volver_a") or url_for("kanban"))


@app.route("/ot/<ot_id>/finalizar", methods=["GET", "POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def ot_finalizar(ot_id):
    ot = query_one("SELECT ot_id, activo_codigo, estado, descripcion_tarea FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,))
    if not ot:
        abort(404)

    checklist = get_checklist_para_activo(ot["activo_codigo"])

    if request.method == "POST":
        codigos = request.form.getlist("repuesto_codigo")
        cantidades = request.form.getlist("repuesto_cantidad")
        repuestos = [
            {"codigo_repuesto": c, "cantidad": int(q)}
            for c, q in zip(codigos, cantidades) if c and q and int(q) > 0
        ]

        checklist_respuestas = []
        if checklist:
            for item in checklist["checklist_items"]:
                iid = item["item_id"]
                if item["tipo_respuesta"] == "boolean":
                    valor = request.form.get(f"check_{iid}")
                    if valor is not None:
                        checklist_respuestas.append({"item_id": iid, "ok": valor == "ok"})
                elif item["tipo_respuesta"] == "numero":
                    valor = request.form.get(f"check_{iid}")
                    if valor:
                        checklist_respuestas.append({"item_id": iid, "valor_numero": float(valor)})
                elif item["tipo_respuesta"] == "texto":
                    valor = request.form.get(f"check_{iid}")
                    if valor:
                        checklist_respuestas.append({"item_id": iid, "valor_texto": valor})
                comentario_item = request.form.get(f"comentario_{iid}")
                if comentario_item and checklist_respuestas and checklist_respuestas[-1]["item_id"] == iid:
                    checklist_respuestas[-1]["comentario"] = comentario_item

        try:
            finalizar_ot(
                ot_id=ot_id, usuario_id=int(current_user.id), repuestos=repuestos,
                checklist_respuestas=checklist_respuestas,
                comentario=request.form.get("comentario") or None, ip_address=request.remote_addr,
            )
            flash(f"{ot_id} finalizada correctamente ({len(repuestos)} repuesto(s) registrado(s)).", "info")
            return redirect(url_for("kanban"))
        except (InvalidTransitionError, BusinessRuleError) as e:
            flash(str(e), "error")

    almacen = query("SELECT codigo_repuesto, nombre, stock_actual FROM core.repuesto_almacen ORDER BY nombre")
    return render_template("ot_finalizar.html", ot=ot, almacen=almacen, checklist=checklist)


@app.route("/ot/<ot_id>/historial")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def ot_historial(ot_id):
    ot = query_one("SELECT ot_id, activo_codigo, estado FROM core.orden_trabajo WHERE ot_id = %s", (ot_id,))
    if not ot:
        abort(404)
    historial = get_historial_ot(ot_id)
    checklist_respuestas = get_checklist_respuestas_ot(ot_id)
    return render_template("ot_historial.html", ot=ot, historial=historial, checklist_respuestas=checklist_respuestas)


@app.route("/activos")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def index():
    return render_template("index.html", activos=get_activos_list())


# ---------------------------------------------------------------------
# Tareas — módulo "Planes de Tareas" del manual de Fracttal (pág. 116+),
# simplificado: listado + creación manual de tareas de mantenimiento
# (además de las que ya llegan por el pipeline ETL).
# ---------------------------------------------------------------------
@app.route("/tareas")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def tareas():
    filtro_estado = request.args.get("estado") or None
    return render_template("tareas.html", tareas=get_tareas_list(estado=filtro_estado), filtro_estado=filtro_estado)


@app.route("/tareas/nueva", methods=["GET", "POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def tarea_nueva():
    if request.method == "POST":
        nombre_tarea = request.form.get("nombre_tarea", "").strip()
        if not nombre_tarea:
            flash("El nombre de la tarea es obligatorio.", "error")
        else:
            tarea_id = f"TAREA-M{uuid.uuid4().hex[:6].upper()}"
            execute(
                "INSERT INTO core.tarea (tarea_id, activo_codigo, nombre_tarea, planificada, frecuencia, fecha_programada, estado) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'Pendiente')",
                (
                    tarea_id, request.form.get("activo_codigo") or None, nombre_tarea,
                    request.form.get("planificada") == "on", request.form.get("frecuencia") or None,
                    request.form.get("fecha_programada") or None,
                ),
            )
            registrar_evento(usuario_id=int(current_user.id), accion="CREAR_TAREA", entidad_tipo="tarea",
                              entidad_id=tarea_id, ip_address=request.remote_addr)
            flash(f"Tarea {tarea_id} creada correctamente.", "info")
            return redirect(url_for("tareas"))

    activos = get_activos_list()
    return render_template(
        "tarea_nueva.html", activos=activos,
        frecuencias=["MENSUAL", "TRIMESTRAL", "SEMESTRAL", "ANUAL"],
        activo_preseleccionado=request.args.get("activo"),
    )


@app.route("/tareas/<tarea_id>/finalizar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def tarea_finalizar(tarea_id):
    execute("UPDATE core.tarea SET estado = 'Finalizada', updated_at = now() WHERE tarea_id = %s", (tarea_id,))
    registrar_evento(usuario_id=int(current_user.id), accion="FINALIZAR_TAREA", entidad_tipo="tarea",
                      entidad_id=tarea_id, ip_address=request.remote_addr)
    flash(f"Tarea {tarea_id} marcada como finalizada.", "info")
    return redirect(url_for("tareas"))


# ---------------------------------------------------------------------
# Calendario y Gantt — vista combinada de Tareas + Órdenes de Trabajo
# (ver captura del manual Fracttal, "Vista Calendario"). Ambas vistas
# comparten la misma fuente de datos (/calendario/eventos.json) y el
# mismo endpoint de reprogramar por arrastre (/calendario/mover).
# ---------------------------------------------------------------------
@app.route("/calendario")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def calendario():
    return render_template("calendario.html")


@app.route("/gantt")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def gantt():
    return render_template("gantt.html")


@app.route("/calendario/eventos.json")
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def calendario_eventos_json():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not desde or not hasta:
        return jsonify({"error": "faltan parámetros 'desde'/'hasta'"}), 400
    return jsonify(get_calendario_eventos(desde, hasta))


@app.route("/calendario/mover", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def calendario_mover():
    data = request.get_json(force=True, silent=True) or {}
    tipo = data.get("tipo")
    evento_id = data.get("id")
    nueva_fecha = data.get("nueva_fecha")
    if not tipo or not evento_id or not nueva_fecha:
        return jsonify({"error": "faltan parámetros"}), 400
    try:
        mover_evento_calendario(tipo, evento_id, nueva_fecha)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    registrar_evento(usuario_id=int(current_user.id), accion=f"REPROGRAMAR_{tipo.upper()}", entidad_tipo=tipo,
                      entidad_id=evento_id, detalles={"nueva_fecha": nueva_fecha}, ip_address=request.remote_addr)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------
# Paginas HTML -- PUBLICAS a proposito (flujo fisico QR / kiosco)
# ---------------------------------------------------------------------
@app.route("/activo/<codigo>")
def activo_detalle(codigo):
    try:
        data = get_activo_detalle(codigo)
    except NotFoundError:
        abort(404)
    uid = int(current_user.id) if current_user.is_authenticated else None
    registrar_evento(usuario_id=uid, accion="VER_ACTIVO_QR", entidad_tipo="activo", entidad_id=codigo,
                      ip_address=request.remote_addr)
    checklist_referencia = get_checklist_para_activo(codigo)
    can_edit = current_user.is_authenticated and current_user.tiene_rol("ADMIN", "SUPERVISOR", "TECNICO")
    return render_template("activo_detalle.html", **data, checklist_referencia=checklist_referencia, can_edit=can_edit)


@app.route("/activo/<codigo>/qr.png")
def activo_qr(codigo):
    """
    Genera el QR AL VUELO usando el mismo host/puerto con el que se
    entró a esta página (request.host_url) — así nunca hay que
    configurar a mano una IP: el QR apunta automáticamente a donde
    sea que esté corriendo la app cuando se genera.
    """
    import io
    import qrcode
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)
    url = f"{request.host_url.rstrip('/')}/activo/{codigo}"
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype="image/png")


@app.route("/activo/<codigo>/foto", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_subir_foto(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)

    archivo = request.files.get("foto")
    if not archivo or archivo.filename == "":
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo))

    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        flash("Formato no soportado. Usa JPG, PNG o WEBP.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo))

    nombre_archivo = f"{codigo}{ext}"
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fotos_activos")
    os.makedirs(carpeta, exist_ok=True)
    archivo.save(os.path.join(carpeta, nombre_archivo))

    execute("UPDATE core.activo SET foto_filename = %s WHERE codigo_activo = %s", (nombre_archivo, codigo))
    registrar_evento(usuario_id=int(current_user.id), accion="SUBIR_FOTO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Foto actualizada correctamente.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo))


# ---------------------------------------------------------------------
# Ficha de activo estilo Fracttal — edición de campos (General +
# Financiero comparten el mismo endpoint porque ambos son "editar
# columnas de core.activo"), Formulario Personalizado (JSONB), Terceros,
# Adjuntos y Gestión Documental. Todo requiere sesión (a diferencia de
# la vista misma del activo, que es pública para el flujo QR).
# ---------------------------------------------------------------------

# campo -> tipo, para saber cómo parsear/validar cada uno al guardar
CAMPOS_ACTIVO_EDITABLES = {
    "nombre": "text", "fabricante": "text", "modelo": "text", "numero_serie": "text",
    "tipo_equipo": "text", "clasificacion_1": "text", "clasificacion_2": "text",
    "criticidad": "text", "numero_pedido": "text", "codigo_barras": "text",
    "fecha_compra": "date", "horas_uso_promedio_diario": "numeric",
    "plan_mantenimiento": "text", "ubicacion_path": "text",
    "nivel_2_sede": "text", "nivel_3_servicio": "text", "proveedor_nombre": "text",
    "visible_para_todos": "bool", "habilitado": "bool", "fuera_de_servicio": "bool",
    "costo_compra": "numeric", "valor_salvamento": "numeric", "vida_util_anios": "numeric",
    "moneda": "text",
}

ADJUNTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "adjuntos_activos")
DOCUMENTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "documentos_activos")
EXTENSIONES_ARCHIVO_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv"}


@app.route("/activo/<codigo>/actualizar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_actualizar(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)

    sets, params = [], []
    for campo, tipo in CAMPOS_ACTIVO_EDITABLES.items():
        if tipo == "bool":
            valor = campo in request.form  # checkbox: presente = true, ausente = false
        elif campo not in request.form:
            continue
        elif tipo == "numeric":
            crudo = request.form.get(campo, "").strip()
            valor = float(crudo) if crudo else None
        elif tipo == "date":
            crudo = request.form.get(campo, "").strip()
            valor = crudo or None
        else:
            crudo = request.form.get(campo, "").strip()
            valor = crudo or None
        sets.append(f"{campo} = %s")
        params.append(valor)

    if sets:
        sets.append("updated_at = now()")
        params.append(codigo)
        execute(f"UPDATE core.activo SET {', '.join(sets)} WHERE codigo_activo = %s", tuple(params))
        registrar_evento(usuario_id=int(current_user.id), accion="EDITAR_ACTIVO", entidad_tipo="activo",
                          entidad_id=codigo, ip_address=request.remote_addr)
        flash("Activo actualizado correctamente.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#" + (request.form.get("volver_a_pestana") or "general"))


@app.route("/activo/<codigo>/formulario", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_formulario_personalizado(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)

    nombres = request.form.getlist("campo_nombre")
    valores = request.form.getlist("campo_valor")
    datos = {n.strip(): v.strip() for n, v in zip(nombres, valores) if n.strip()}

    execute("UPDATE core.activo SET formulario_personalizado = %s, updated_at = now() WHERE codigo_activo = %s",
            (Json(datos), codigo))
    registrar_evento(usuario_id=int(current_user.id), accion="EDITAR_FORMULARIO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Formulario personalizado actualizado.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#formulario")


@app.route("/activo/<codigo>/terceros/nuevo", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_tercero_nuevo(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre del tercero es obligatorio.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo) + "#terceros")

    execute(
        """
        INSERT INTO core.activo_tercero (activo_codigo, tipo, nombre, contacto_nombre, telefono, email, notas)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (codigo, request.form.get("tipo") or "Proveedor", nombre,
         request.form.get("contacto_nombre") or None, request.form.get("telefono") or None,
         request.form.get("email") or None, request.form.get("notas") or None),
    )
    registrar_evento(usuario_id=int(current_user.id), accion="CREAR_TERCERO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Tercero agregado correctamente.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#terceros")


@app.route("/activo/<codigo>/terceros/<int:tercero_id>/eliminar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_tercero_eliminar(codigo, tercero_id):
    execute("DELETE FROM core.activo_tercero WHERE tercero_id = %s AND activo_codigo = %s", (tercero_id, codigo))
    registrar_evento(usuario_id=int(current_user.id), accion="ELIMINAR_TERCERO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Tercero eliminado.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#terceros")


def _guardar_archivo_subido(archivo, carpeta, codigo):
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        return None, None
    os.makedirs(carpeta, exist_ok=True)
    nombre_archivo = f"{codigo}_{uuid.uuid4().hex[:8]}{ext}"
    ruta = os.path.join(carpeta, nombre_archivo)
    archivo.save(ruta)
    return nombre_archivo, os.path.getsize(ruta)


@app.route("/activo/<codigo>/adjuntos", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_adjunto_subir(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)
    archivo = request.files.get("archivo")
    if not archivo or archivo.filename == "":
        flash("No se seleccionó ningún archivo.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo) + "#adjuntos")

    nombre_archivo, tamano = _guardar_archivo_subido(archivo, ADJUNTOS_DIR, codigo)
    if not nombre_archivo:
        flash("Formato no soportado.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo) + "#adjuntos")

    execute(
        "INSERT INTO core.activo_adjunto (activo_codigo, nombre_original, archivo_filename, tamano_bytes, subido_por_usuario_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (codigo, archivo.filename, nombre_archivo, tamano, int(current_user.id)),
    )
    registrar_evento(usuario_id=int(current_user.id), accion="SUBIR_ADJUNTO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Adjunto subido correctamente.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#adjuntos")


@app.route("/activo/<codigo>/adjuntos/<int:adjunto_id>/descargar")
def activo_adjunto_descargar(codigo, adjunto_id):
    adjunto = query_one("SELECT nombre_original, archivo_filename FROM core.activo_adjunto "
                         "WHERE adjunto_id = %s AND activo_codigo = %s", (adjunto_id, codigo))
    if not adjunto:
        abort(404)
    return send_from_directory(ADJUNTOS_DIR, adjunto["archivo_filename"], as_attachment=True,
                                download_name=adjunto["nombre_original"])


@app.route("/activo/<codigo>/adjuntos/<int:adjunto_id>/eliminar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_adjunto_eliminar(codigo, adjunto_id):
    adjunto = query_one("SELECT archivo_filename FROM core.activo_adjunto WHERE adjunto_id = %s AND activo_codigo = %s",
                         (adjunto_id, codigo))
    if adjunto:
        execute("DELETE FROM core.activo_adjunto WHERE adjunto_id = %s AND activo_codigo = %s", (adjunto_id, codigo))
        ruta = os.path.join(ADJUNTOS_DIR, adjunto["archivo_filename"])
        if os.path.exists(ruta):
            os.remove(ruta)
        registrar_evento(usuario_id=int(current_user.id), accion="ELIMINAR_ADJUNTO_ACTIVO", entidad_tipo="activo",
                          entidad_id=codigo, ip_address=request.remote_addr)
        flash("Adjunto eliminado.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#adjuntos")


@app.route("/activo/<codigo>/documentos", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_documento_subir(codigo):
    activo = query_one("SELECT codigo_activo FROM core.activo WHERE codigo_activo = %s", (codigo,))
    if not activo:
        abort(404)
    archivo = request.files.get("archivo")
    nombre = request.form.get("nombre", "").strip()
    if not archivo or archivo.filename == "" or not nombre:
        flash("Nombre del documento y archivo son obligatorios.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo) + "#documental")

    nombre_archivo, _ = _guardar_archivo_subido(archivo, DOCUMENTOS_DIR, codigo)
    if not nombre_archivo:
        flash("Formato no soportado.", "error")
        return redirect(url_for("activo_detalle", codigo=codigo) + "#documental")

    execute(
        """
        INSERT INTO core.activo_documento (activo_codigo, categoria, nombre, archivo_filename, version, fecha_vigencia, subido_por_usuario_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (codigo, request.form.get("categoria") or "Otro", nombre, nombre_archivo,
         request.form.get("version") or None, request.form.get("fecha_vigencia") or None, int(current_user.id)),
    )
    registrar_evento(usuario_id=int(current_user.id), accion="SUBIR_DOCUMENTO_ACTIVO", entidad_tipo="activo",
                      entidad_id=codigo, ip_address=request.remote_addr)
    flash("Documento agregado correctamente.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#documental")


@app.route("/activo/<codigo>/documentos/<int:documento_id>/descargar")
def activo_documento_descargar(codigo, documento_id):
    documento = query_one("SELECT nombre, archivo_filename FROM core.activo_documento "
                           "WHERE documento_id = %s AND activo_codigo = %s", (documento_id, codigo))
    if not documento:
        abort(404)
    ext = os.path.splitext(documento["archivo_filename"])[1]
    return send_from_directory(DOCUMENTOS_DIR, documento["archivo_filename"], as_attachment=True,
                                download_name=documento["nombre"] + ext)


@app.route("/activo/<codigo>/documentos/<int:documento_id>/eliminar", methods=["POST"])
@role_required("ADMIN", "SUPERVISOR", "TECNICO")
def activo_documento_eliminar(codigo, documento_id):
    documento = query_one("SELECT archivo_filename FROM core.activo_documento WHERE documento_id = %s AND activo_codigo = %s",
                           (documento_id, codigo))
    if documento:
        execute("DELETE FROM core.activo_documento WHERE documento_id = %s AND activo_codigo = %s", (documento_id, codigo))
        ruta = os.path.join(DOCUMENTOS_DIR, documento["archivo_filename"])
        if os.path.exists(ruta):
            os.remove(ruta)
        registrar_evento(usuario_id=int(current_user.id), accion="ELIMINAR_DOCUMENTO_ACTIVO", entidad_tipo="activo",
                          entidad_id=codigo, ip_address=request.remote_addr)
        flash("Documento eliminado.", "info")
    return redirect(url_for("activo_detalle", codigo=codigo) + "#documental")


@app.route("/panel/hoy")
def panel_hoy():
    return render_template("panel_hoy.html", **get_panel_hoy_data())


# ---------------------------------------------------------------------
# Administracion de usuarios -- solo ADMIN
# ---------------------------------------------------------------------
@app.route("/admin/usuarios")
@role_required("ADMIN")
def admin_usuarios():
    usuarios = query(
        "SELECT usuario_id, username, nombre_completo, rol, activo, ultimo_login "
        "FROM core.usuario ORDER BY rol, username"
    )
    return render_template("admin_usuarios.html", usuarios=usuarios)


@app.route("/auditoria")
@role_required("ADMIN", "SUPERVISOR")
def auditoria():
    filtro_accion = request.args.get("accion") or None
    eventos = get_eventos(accion=filtro_accion, limit=300)
    acciones = get_acciones_distintas()
    return render_template("auditoria.html", eventos=eventos, acciones=acciones, filtro_accion=filtro_accion)


@app.route("/automatizador")
@role_required("ADMIN", "SUPERVISOR")
def automatizador():
    """
    Vista de solo lectura del sistema de eventos dinámico (ver
    transform/events.py) — análoga al módulo "Automatizador" de
    Fracttal (manual, pág. 202+): reglas de datos que disparan acciones
    automáticas. Acá se ven los eventos que ya se dispararon.
    """
    filtro_modulo = request.args.get("modulo") or None
    sql = (
        "SELECT evento_id, modulo, evento_nombre, record_key, accion, resultado, detalles, fecha "
        "FROM core.evento_automatizacion WHERE 1=1"
    )
    params: list = []
    if filtro_modulo:
        sql += " AND modulo = %s"
        params.append(filtro_modulo)
    sql += " ORDER BY fecha DESC LIMIT 300"
    eventos = query(sql, tuple(params))
    modulos = [r["modulo"] for r in query("SELECT DISTINCT modulo FROM core.evento_automatizacion ORDER BY modulo")]
    return render_template("automatizador.html", eventos=eventos, modulos=modulos, filtro_modulo=filtro_modulo)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5090)), debug=debug_mode)
