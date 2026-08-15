"""
Generador de datos DEMO para el CMMS clínico.

Implementa la MISMA interfaz pública que FracttalClient (get_activos,
get_ordenes_trabajo, get_tareas, get_medidores, get_lecturas_medidor,
get_almacenes, get_recursos_humanos) para que los DAGs de Airflow
funcionen igual sin importar la fuente.

Uso:
    from connectors.demo_data_generator import DemoFracttalClient
    client = DemoFracttalClient(seed=42)
    for activo in client.get_activos():
        ...

Diseñado para una clínica internacional: jerarquía de sedes e
infraestructura crítica de planta física (energía, climatización,
bombeo, gases medicinales, eléctrico) — NO equipamiento biomédico de
atención al paciente.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator

# ---------------------------------------------------------------------
# Catálogos base — equipamiento clínico / biomédico
# ---------------------------------------------------------------------
SEDES = ["Sede Lima", "Sede Bogotá", "Sede Ciudad de México", "Sede Miami"]

# Áreas/sistemas de infraestructura crítica de la clínica (NO equipamiento
# biomédico de atención al paciente — esto es la planta física: energía,
# climatización, agua, gases medicinales, eléctrico).
SERVICIOS_CLINICOS = [
    "Planta de Generación Eléctrica", "Sala de Climatización", "Cuarto de Bombas",
    "Central de Gases Medicinales", "Subestación Eléctrica", "Sala de Transformadores",
    "Sala de Tableros Eléctricos", "Cuarto de Máquinas", "Azotea Técnica",
]

TIPOS_EQUIPO = [
    ("Generador Eléctrico de Emergencia", "Alto", ["Cummins", "Caterpillar", "Perkins", "Cummins Power Generation"]),
    ("UPS - Sistema de Energía Ininterrumpida", "Alto", ["Schneider Electric", "Eaton", "ABB", "Vertiv"]),
    ("Chiller de Climatización", "Alto", ["AAON", "Trane", "Carrier", "York"]),
    ("Unidad Manejadora de Aire (UMA)", "Alto", ["Trane", "Carrier", "Daikin"]),
    ("Unidad de Aire Acondicionado de Precisión", "Alto", ["Liebert (Vertiv)", "Stulz", "AAON"]),
    ("Bomba de Succión", "Alto", ["Grundfos", "Goulds Pumps", "Xylem"]),
    ("Bomba de Agua", "Medio", ["Grundfos", "Pedrollo", "Xylem"]),
    ("Bomba de Vacío", "Alto", ["Becker", "Busch", "Powerex"]),
    ("Ablandador de Agua", "Medio", ["Culligan", "EcoWater", "Pentair"]),
    ("Sistema Central de Oxígeno Medicinal", "Alto", ["Amico", "Beacon Medaes", "Powerex"]),
    ("Transformador Eléctrico", "Alto", ["Siemens", "ABB", "Schneider Electric"]),
    ("Tablero Eléctrico Principal", "Alto", ["Schneider Electric", "ABB", "Siemens"]),
    ("Torre de Enfriamiento", "Medio", ["BAC", "Evapco", "Marley"]),
    ("Subestación Eléctrica Compacta", "Alto", ["Siemens", "ABB", "Schneider Electric"]),
]

RESPONSABLES = [
    ("Ing. María Fernanda Rojas", "Ingeniera Electromecánica"),
    ("Téc. Carlos Andrade", "Técnico Electricista Industrial"),
    ("Ing. Luis Peña", "Ingeniero de Climatización Senior"),
    ("Téc. Sofía Vargas", "Técnica en Refrigeración y HVAC"),
    ("Ing. Roberto Chávez", "Jefe de Infraestructura y Mantenimiento"),
]

PROVEEDORES = [
    ("AAON Servicio Técnico LatAm", "Fabricante / Servicio Técnico"),
    ("Cummins Power Generation", "Fabricante / Servicio Técnico"),
    ("Grupo Electromecánico Andino SAC", "Servicio Técnico Externo"),
    ("Schneider Electric Field Services", "Fabricante / Servicio Técnico"),
    ("Metrología Industrial Internacional", "Calibración e Instrumentación"),
]

TIPOS_OT = ["CORRECTIVO", "PREVENTIVO", "CALIBRACION", "OVERHAUL"]
ESTADOS_OT = ["Pendiente", "En Proceso", "En Revisión", "Finalizada"]
CLASIFICACIONES = ["GESTION ELECTROMECANICA", "GESTION MECANICA", "GESTION ELECTRICA", "CLIMATIZACION Y HVAC"]


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


class DemoFracttalClient:
    def __init__(self, seed: int | None = 42, n_activos: int = 120):
        self.rng = random.Random(seed)
        self.n_activos = n_activos
        self._activos_cache: list[dict] | None = None
        self._ots_cache: list[dict] | None = None
        self._almacenes_cache: list[dict] | None = None

    # ------------------------------------------------------------------
    def _gen_activos(self) -> list[dict]:
        if self._activos_cache is not None:
            return self._activos_cache

        activos = []
        for i in range(1, self.n_activos + 1):
            tipo, riesgo, fabricantes = self.rng.choice(TIPOS_EQUIPO)
            sede = self.rng.choice(SEDES)
            servicio = self.rng.choice(SERVICIOS_CLINICOS)
            fabricante = self.rng.choice(fabricantes)
            fecha_compra = datetime(2018, 1, 1) + timedelta(days=self.rng.randint(0, 2500))
            ultima_calib = datetime.now() - timedelta(days=self.rng.randint(10, 400))
            proxima_calib = ultima_calib + timedelta(days=365)

            activos.append({
                "codigo": f"EQ-{i:04d}",
                "nombre": f"{tipo} {i:03d}",
                "fabricante": fabricante,
                "modelo": f"MOD-{self.rng.randint(100,999)}",
                "numero_serie": str(uuid.uuid4())[:12].upper(),
                "tipo_equipo": tipo,
                "clasificacion_riesgo": riesgo,
                "criticidad": self.rng.choice(["Muy Alta", "Alta", "Media", "Baja"]),
                "ubicacion_path": f"CLINICA_INTL/{sede.replace(' ', '_')}/{servicio.replace(' ', '_')}",
                "nivel_1_institucion": "Clínica Internacional",
                "nivel_2_sede": sede,
                "nivel_3_servicio": servicio,
                "proveedor": self.rng.choice(PROVEEDORES)[0],
                "fecha_compra": fecha_compra.date().isoformat(),
                "fecha_ultima_calibracion": ultima_calib.date().isoformat(),
                "proxima_calibracion": proxima_calib.date().isoformat(),
                "fuera_de_servicio": self.rng.random() < 0.05,
                "habilitado": True,
                "plan_mantenimiento": f"PLAN MTO {tipo.upper()}",
                "horas_uso_promedio_diario": round(self.rng.uniform(2, 24), 1),
                "costo_compra": round(self.rng.uniform(5000, 250000), 2),
                "valor_salvamento": 0,
                "vida_util_anios": self.rng.choice([5, 7, 10]),
                "updated_at": _iso(datetime.utcnow()),
            })
        self._activos_cache = activos
        return activos

    def get_activos(self, updated_since: str | None = None) -> Iterator[dict]:
        yield from self._gen_activos()

    def get_recursos_humanos(self) -> Iterator[dict]:
        for i, (nombre, rol) in enumerate(RESPONSABLES, start=1):
            yield {
                "codigo": f"RH-{i:03d}",
                "nombre_completo": nombre,
                "rol": rol,
                "email": nombre.lower().replace(" ", ".").replace("í", "i").replace("é", "e") + "@clinica-intl.com",
                "updated_at": _iso(datetime.utcnow()),
            }

    def _gen_ordenes_trabajo(self, n: int = 100) -> list[dict]:
        if self._ots_cache is not None:
            return self._ots_cache
        activos = self._gen_activos()
        ots = []
        for i in range(1, n + 1):
            activo = self.rng.choice(activos)
            estado = self.rng.choices(ESTADOS_OT, weights=[15, 30, 10, 45])[0]
            tipo_ot = self.rng.choice(TIPOS_OT)
            # Fuerza que un grupo de OTs quede programado para HOY, así el
            # tablero de kiosco (/panel/hoy) siempre tiene datos que mostrar.
            if i <= 10:
                fecha_programada = datetime.now()
                estado = self.rng.choices(["Pendiente", "En Proceso"], weights=[60, 40])[0]
            else:
                fecha_programada = datetime.now() - timedelta(days=self.rng.randint(-10, 60))
            fecha_realizacion = None
            avance = 0
            if estado == "Finalizada":
                fecha_realizacion = fecha_programada + timedelta(days=self.rng.randint(0, 3))
                avance = 100
            elif estado == "En Proceso":
                avance = self.rng.choice([0, 25, 50, 75])
            elif estado == "En Revisión":
                avance = 100

            ots.append({
                "ot_id": f"OT-{1000+i}-PS",
                "codigo_activo": activo["codigo"],
                "responsable": self.rng.choice(RESPONSABLES)[0],
                "tipo_ot": tipo_ot,
                "descripcion_tarea": f"{tipo_ot.title()} — {activo['tipo_equipo']}",
                "estado": estado,
                "clasificacion_1": self.rng.choice(CLASIFICACIONES),
                "fecha_programada": fecha_programada.date().isoformat(),
                "fecha_calculada": fecha_programada.date().isoformat(),
                "fecha_realizacion": fecha_realizacion.date().isoformat() if fecha_realizacion else None,
                "porcentaje_avance": avance,
                "prioridad": self.rng.choice(["Muy Alta", "Alta", "Media", "Baja"]),
                "tiempo_fuera_servicio_horas": round(self.rng.uniform(0, 48), 1) if tipo_ot == "CORRECTIVO" else 0,
                "updated_at": _iso(datetime.utcnow()),
            })
        self._ots_cache = ots
        return ots

    def get_ordenes_trabajo(self, updated_since: str | None = None, n: int = 100) -> Iterator[dict]:
        yield from self._gen_ordenes_trabajo(n)

    def get_tareas(self, updated_since: str | None = None, n: int = 250) -> Iterator[dict]:
        activos = self._gen_activos()
        frecuencias = ["MENSUAL", "TRIMESTRAL", "SEMESTRAL", "ANUAL"]
        for i in range(1, n + 1):
            activo = self.rng.choice(activos)
            fecha_programada = datetime.now() if i <= 8 else (datetime.now() + timedelta(days=self.rng.randint(-5, 45)))
            yield {
                "tarea_id": f"TAREA-{2000+i}",
                "codigo_activo": activo["codigo"],
                "ot_id": None,
                "nombre_tarea": f"Inspección {self.rng.choice(frecuencias).lower()} — {activo['tipo_equipo']}",
                "planificada": self.rng.random() > 0.15,
                "frecuencia": self.rng.choice(frecuencias),
                "fecha_programada": fecha_programada.date().isoformat(),
                "estado": "Pendiente" if i <= 8 else self.rng.choice(["Pendiente", "Finalizada"]),
                "updated_at": _iso(datetime.utcnow()),
            }

    def get_medidores(self) -> Iterator[dict]:
        activos = [a for a in self._gen_activos() if a["tipo_equipo"] in
                   ("Generador Eléctrico de Emergencia", "Chiller de Climatización",
                    "Bomba de Vacío", "Sistema Central de Oxígeno Medicinal",
                    "Transformador Eléctrico")]
        variable_por_tipo = {
            "Generador Eléctrico de Emergencia": ("Temperatura Motor", "C", 95.0),
            "Chiller de Climatización": ("Temperatura Agua Salida", "C", 12.0),
            "Bomba de Vacío": ("Presión de Vacío", "inHg", 25.0),
            "Sistema Central de Oxígeno Medicinal": ("Presión O2 Línea", "psi", 55.0),
            "Transformador Eléctrico": ("Temperatura Devanado", "C", 105.0),
        }
        for activo in activos:
            var_nombre, unidad, umbral = variable_por_tipo[activo["tipo_equipo"]]
            yield {
                "medidor_id": f"MED-{activo['codigo']}",
                "codigo_activo": activo["codigo"],
                "nombre_medidor": f"{var_nombre} - {activo['nombre']}",
                "tipo_variable": var_nombre,
                "unidad": unidad,
                "valor_umbral_alerta": umbral,
            }

    def get_lecturas_medidor(self, medidor_id: str, desde: str, hasta: str) -> Iterator[dict]:
        d0 = datetime.fromisoformat(desde)
        d1 = datetime.fromisoformat(hasta)
        cur = d0
        base = self.rng.uniform(20, 30)
        while cur <= d1:
            valor = round(base + self.rng.uniform(-3, 3), 2)
            yield {
                "medidor_id": medidor_id,
                "fecha_lectura": _iso(cur),
                "valor": valor,
                "en_alerta": valor > base + 2.5,
            }
            cur += timedelta(hours=6)

    def _gen_almacenes(self) -> list[dict]:
        if self._almacenes_cache is not None:
            return self._almacenes_cache
        repuestos = [
            "Correa de transmisión industrial", "Filtro de aire para chiller",
            "Batería de arranque generador 12V", "Sello mecánico bomba centrífuga",
            "Contactor eléctrico 3 polos", "Refrigerante R-410A (cilindro)",
            "Resina para ablandador de agua", "Válvula solenoide de gas medicinal",
            "Rodamiento para motor eléctrico", "Termostato industrial",
        ]
        items = [{
            "codigo_repuesto": f"REP-{i:03d}",
            "nombre": nombre,
            "almacen": "Almacén Central de Infraestructura",
            "stock_actual": self.rng.randint(0, 50),
            "stock_minimo": self.rng.randint(5, 15),
            "costo_unitario": round(self.rng.uniform(10, 800), 2),
            "updated_at": _iso(datetime.utcnow()),
        } for i, nombre in enumerate(repuestos, start=1)]
        self._almacenes_cache = items
        return items

    def get_almacenes(self) -> Iterator[dict]:
        yield from self._gen_almacenes()

    def get_repuestos_usados(self, n_ots: int = 100) -> Iterator[dict]:
        """
        Asocia repuestos consumidos a las OTs correctivas/overhaul —
        necesario para mostrar "repuestos usados" en la página de detalle
        del activo al escanear el QR.
        """
        ots = self._gen_ordenes_trabajo(n_ots)
        repuestos = self._gen_almacenes()
        for ot in ots:
            if ot["tipo_ot"] not in ("CORRECTIVO", "OVERHAUL"):
                continue
            if self.rng.random() > 0.6:   # no todas las OTs consumen repuestos
                continue
            usados = self.rng.sample(repuestos, k=self.rng.randint(1, 3))
            for rep in usados:
                yield {
                    "ot_id": ot["ot_id"],
                    "codigo_repuesto": rep["codigo_repuesto"],
                    "cantidad": self.rng.randint(1, 4),
                }


if __name__ == "__main__":
    # Smoke test rápido
    c = DemoFracttalClient()
    activos = list(c.get_activos())
    ots = list(c.get_ordenes_trabajo(n=20))
    print(f"Activos generados: {len(activos)}")
    print(f"OTs generadas: {len(ots)}")
    print("Ejemplo activo:", activos[0])
    print("Ejemplo OT:", ots[0])
