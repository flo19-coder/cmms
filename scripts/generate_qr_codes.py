"""
Genera un código QR por cada activo del schema `mart`, más una hoja
imprimible (HTML) para pegar en el equipo físico
(ej. Chiller AAON — azotea piso 13).

Cada QR apunta a: <QR_BASE_URL>/activo/<codigo_activo>
Al escanearlo desde el celular, un operador/inspector cae directo en la
ficha del equipo (webapp/app.py).

Uso:
    QR_BASE_URL=http://192.168.1.50:5090 python3 scripts/generate_qr_codes.py
    (usa la IP de esta máquina en la red local de la clínica, no
    "localhost", para que funcione al escanear desde un celular)
"""
import os
import psycopg2
import psycopg2.extras
import qrcode

DB_PARAMS = {
    "host": os.environ.get("CMMS_DW_HOST", "localhost"),
    "port": os.environ.get("CMMS_DW_PORT", "5432"),
    "dbname": os.environ.get("CMMS_DW_NAME", "cmms_dw"),
    "user": os.environ.get("CMMS_DW_USER", "cmms_admin"),
    "password": os.environ.get("CMMS_DW_PASSWORD", "cmms_local_pw_change_me"),
}
QR_BASE_URL = os.environ.get("QR_BASE_URL", "http://localhost:5090")
OUT_DIR = os.environ.get("QR_OUT_DIR", "qr_codes")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = psycopg2.connect(**DB_PARAMS)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT codigo_activo, nombre, nivel_2_sede, nivel_3_servicio, tipo_equipo "
            "FROM mart.dim_activo ORDER BY nivel_2_sede, nivel_3_servicio, codigo_activo"
        )
        activos = cur.fetchall()
    conn.close()

    cards_html = []
    for a in activos:
        url = f"{QR_BASE_URL}/activo/{a['codigo_activo']}"
        img = qrcode.make(url, box_size=8, border=2)
        path = os.path.join(OUT_DIR, f"{a['codigo_activo']}.png")
        img.save(path)

        cards_html.append(f"""
        <div class="card">
          <img src="{a['codigo_activo']}.png" width="140" height="140">
          <div class="meta">
            <strong>{a['nombre']}</strong><br>
            {a['codigo_activo']}<br>
            <span class="loc">{a['nivel_2_sede']} · {a['nivel_3_servicio']}</span>
          </div>
        </div>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8">
    <title>Hoja de etiquetas QR — {len(activos)} activos</title>
    <style>
      body {{ font-family: Arial, sans-serif; background: #f4f8f8; }}
      .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; padding: 20px; }}
      .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 10px; text-align: center; page-break-inside: avoid; }}
      .meta {{ font-size: 11px; margin-top: 6px; line-height: 1.4; }}
      .loc {{ color: #5c7a7d; }}
      @media print {{ body {{ background: white; }} }}
    </style></head>
    <body><div class="grid">{"".join(cards_html)}</div></body></html>"""

    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"{len(activos)} códigos QR generados en '{OUT_DIR}/'")
    print(f"Hoja imprimible: {OUT_DIR}/index.html  (ábrela en el navegador e imprime)")
    print(f"Base URL usada: {QR_BASE_URL}  (cambiar con QR_BASE_URL si no es correcta)")


if __name__ == "__main__":
    main()
