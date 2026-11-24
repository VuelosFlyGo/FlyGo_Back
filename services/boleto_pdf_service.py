from io import BytesIO
import psycopg2.extras
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from database import Database


class BoletoPdfService:
    NAVY = HexColor("#15224B")
    BLUE = HexColor("#3157F5")
    MUTED = HexColor("#6F7890")
    LINE = HexColor("#DDE3F1")

    def obtener_reserva(self, usuario_id, reserva_id):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cursor.execute("""
                SELECT
                    r.id, r.codigo_reserva, r.total, r.estado,
                    u.nombre_completo,
                    v.aerolinea, v.origen, v.destino, v.fecha,
                    v.hora_salida, v.hora_llegada,
                    COALESCE(
                        ARRAY_AGG(av.numero_asiento ORDER BY av.numero_asiento)
                        FILTER (WHERE av.numero_asiento IS NOT NULL),
                        ARRAY[]::VARCHAR[]
                    ) AS asientos
                FROM reservas r
                JOIN usuarios u ON u.id = r.usuario_id
                JOIN vuelos v ON v.id = r.vuelo_id
                LEFT JOIN asientos_vuelo av ON av.reserva_id = r.id
                WHERE r.id = %s AND r.usuario_id = %s AND r.estado = 'ACTIVA'
                GROUP BY r.id, u.nombre_completo, v.id
            """, (reserva_id, usuario_id))
            return cursor.fetchone()
        finally:
            cursor.close()
            conexion.close()

    def generar(self, reserva):
        salida = BytesIO()
        pdf = canvas.Canvas(salida, pagesize=A4)
        ancho, alto = A4
        asientos = list(reserva["asientos"])

        for indice, asiento in enumerate(asientos):
            posicion = indice % 2
            if posicion == 0 and indice > 0:
                pdf.showPage()

            ticket_alto = 330
            margen = 34
            y = alto - margen - ticket_alto if posicion == 0 else margen
            self._dibujar_boleto(pdf, margen, y, ancho - margen * 2, ticket_alto, reserva, asiento)

        pdf.setTitle(f"Boletos FlyGo {reserva['codigo_reserva']}")
        pdf.setAuthor("FlyGo")
        pdf.save()
        salida.seek(0)
        return salida

    def _dibujar_boleto(self, pdf, x, y, ancho, alto, reserva, asiento):
        corte = x + ancho * .76
        pdf.setFillColor(white)
        pdf.setStrokeColor(self.LINE)
        pdf.roundRect(x, y, ancho, alto, 16, fill=1, stroke=1)

        pdf.setFillColor(self.NAVY)
        pdf.roundRect(x, y + alto - 64, ancho, 64, 16, fill=1, stroke=0)
        pdf.rect(x, y + alto - 64, ancho, 18, fill=1, stroke=0)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 23)
        pdf.drawString(x + 24, y + alto - 41, "FLYGO")
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawRightString(x + ancho - 24, y + alto - 39, "PASE DE ABORDAR")

        pdf.setStrokeColor(self.MUTED)
        pdf.setDash(4, 4)
        pdf.line(corte, y + 18, corte, y + alto - 78)
        pdf.setDash()

        izquierda = x + 26
        centro = x + ancho * .43
        top = y + alto - 98
        self._campo(pdf, izquierda, top, "PASAJERO", reserva["nombre_completo"])
        self._campo(pdf, centro, top, "VUELO", f"FG{reserva['id']:05d}")
        self._campo(pdf, izquierda, top - 58, "RUTA", f"{reserva['origen']} - {reserva['destino']}")
        self._campo(pdf, centro, top - 58, "ASIENTO", asiento, grande=True)
        self._campo(pdf, izquierda, top - 116, "FECHA", str(reserva["fecha"]))
        self._campo(pdf, centro, top - 116, "SALIDA", str(reserva["hora_salida"])[:5])

        barra = code128.Code128(
            f"{reserva['codigo_reserva']}-{asiento}",
            barHeight=32,
            barWidth=.75,
        )
        barra.drawOn(pdf, izquierda, y + 35)
        pdf.setFillColor(self.MUTED)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(izquierda, y + 23, reserva["codigo_reserva"])

        talon_x = corte + 18
        pdf.setFillColor(self.BLUE)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(talon_x, top, "FLYGO")
        pdf.setFillColor(self.NAVY)
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(talon_x, top - 45, asiento)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(talon_x, top - 72, f"FG{reserva['id']:05d}")
        pdf.setFillColor(self.MUTED)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(talon_x, top - 100, str(reserva["fecha"]))
        pdf.drawString(talon_x, top - 116, str(reserva["hora_salida"])[:5])
        pdf.setStrokeColor(self.BLUE)
        pdf.setLineWidth(2)
        pdf.line(talon_x, y + 55, x + ancho - 22, y + 55)
        pdf.setFillColor(self.NAVY)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(talon_x, y + 38, "PRESENTAR EN PUERTA")

    def _campo(self, pdf, x, y, etiqueta, valor, grande=False):
        pdf.setFillColor(self.MUTED)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y, etiqueta)
        pdf.setFillColor(self.NAVY)
        pdf.setFont("Helvetica-Bold", 18 if grande else 11)
        pdf.drawString(x, y - 18, str(valor)[:35])
