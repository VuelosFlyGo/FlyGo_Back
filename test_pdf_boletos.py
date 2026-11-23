from datetime import date, time
from pathlib import Path

from services.boleto_pdf_service import BoletoPdfService


def ejecutar():
    reserva = {
        "id": 38,
        "codigo_reserva": "FG-DEMO-2026",
        "nombre_completo": "Alex Peñafiel",
        "aerolinea": "FlyGo",
        "origen": "Quito",
        "destino": "Guayaquil",
        "fecha": date(2027, 6, 10),
        "hora_salida": time(8, 0),
        "hora_llegada": time(9, 0),
        "asientos": ["2A", "2B", "2C"],
        "total": 255,
        "estado": "ACTIVA",
    }
    salida = Path("output/pdf/flygo_boletos_muestra.pdf")
    salida.parent.mkdir(parents=True, exist_ok=True)
    buffer = BoletoPdfService().generar(reserva)
    salida.write_bytes(buffer.read())
    assert salida.stat().st_size > 2000
    print(salida.resolve())


if __name__ == "__main__":
    ejecutar()
