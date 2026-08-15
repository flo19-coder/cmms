"""
Crea plantillas de checklist de mantenimiento para los tipos de equipo
de infraestructura crítica del proyecto (generadores, chillers, bombas,
transformadores, etc.) — para que al finalizar una OT sobre esos
equipos aparezca el checklist correspondiente.

Idempotente: si una plantilla con el mismo nombre ya existe, se omite.

Uso:
    python3 scripts/seed_checklists.py
"""
import os
import sys

import psycopg2
import psycopg2.extras

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}

# (nombre_plantilla, tipo_equipo, [(descripcion, tipo_respuesta, obligatorio), ...])
CHECKLISTS = [
    ("Mantenimiento preventivo — Generador eléctrico", "Generador Eléctrico de Emergencia", [
        ("Nivel de aceite dentro de rango", "boolean", True),
        ("Nivel de refrigerante dentro de rango", "boolean", True),
        ("Batería de arranque — voltaje (V)", "numero", True),
        ("Prueba de arranque en frío exitosa", "boolean", True),
        ("Fugas visibles de combustible o aceite", "boolean", True),
        ("Estado del filtro de aire", "boolean", False),
        ("Ruido/vibración anormal durante arranque", "boolean", False),
        ("Observaciones generales", "texto", False),
    ]),
    ("Mantenimiento preventivo — Chiller / Climatización", "Chiller de Climatización", [
        ("Presión de refrigerante (psi)", "numero", True),
        ("Temperatura de agua de salida (°C)", "numero", True),
        ("Estado de correas y poleas", "boolean", True),
        ("Fugas de refrigerante", "boolean", True),
        ("Limpieza de condensador realizada", "boolean", False),
        ("Ruido/vibración anormal", "boolean", False),
        ("Observaciones generales", "texto", False),
    ]),
    ("Mantenimiento preventivo — Bomba (succión/agua/vacío)", "Bomba de Succión", [
        ("Presión de descarga dentro de rango", "boolean", True),
        ("Fugas en sellos mecánicos", "boolean", True),
        ("Vibración dentro de límites normales", "boolean", True),
        ("Temperatura de rodamientos (°C)", "numero", False),
        ("Lubricación verificada", "boolean", False),
        ("Observaciones generales", "texto", False),
    ]),
    ("Mantenimiento preventivo — Transformador eléctrico", "Transformador Eléctrico", [
        ("Temperatura de devanado (°C)", "numero", True),
        ("Nivel de aceite dielétrico", "boolean", True),
        ("Fugas de aceite visibles", "boolean", True),
        ("Conexiones y terminales sin sobrecalentamiento", "boolean", True),
        ("Ruido anormal (zumbido excesivo)", "boolean", False),
        ("Observaciones generales", "texto", False),
    ]),
    ("Mantenimiento preventivo — Sistema de oxígeno medicinal", "Sistema Central de Oxígeno Medicinal", [
        ("Presión de línea dentro de rango (psi)", "numero", True),
        ("Alarmas de presión funcionando correctamente", "boolean", True),
        ("Fugas detectadas en la red", "boolean", True),
        ("Válvulas de corte accesibles y rotuladas", "boolean", True),
        ("Reserva/suministro de respaldo verificado", "boolean", True),
        ("Observaciones generales", "texto", False),
    ]),
]


def main():
    conn = psycopg2.connect(**DB_PARAMS)
    creadas = 0
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for nombre, tipo_equipo, items in CHECKLISTS:
                cur.execute("SELECT checklist_template_id FROM core.checklist_template WHERE nombre = %s", (nombre,))
                existing = cur.fetchone()
                if existing:
                    print(f"'{nombre}' ya existe, se omite.")
                    continue

                cur.execute(
                    "INSERT INTO core.checklist_template (nombre, tipo_equipo) VALUES (%s, %s) RETURNING checklist_template_id",
                    (nombre, tipo_equipo),
                )
                template_id = cur.fetchone()["checklist_template_id"]

                for orden, (descripcion, tipo_respuesta, obligatorio) in enumerate(items, start=1):
                    cur.execute(
                        "INSERT INTO core.checklist_template_item (checklist_template_id, orden, descripcion, tipo_respuesta, obligatorio) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (template_id, orden, descripcion, tipo_respuesta, obligatorio),
                    )
                creadas += 1
                print(f"Creado: '{nombre}' ({len(items)} ítems) → tipo_equipo='{tipo_equipo}'")
        conn.commit()
    finally:
        conn.close()
    print(f"\n{creadas} plantilla(s) de checklist creada(s).")


if __name__ == "__main__":
    main()
