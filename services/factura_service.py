from datetime import datetime
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET

import psycopg2.extras
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from database import Database


class FacturaService:
    """Genera comprobantes académicos a partir de una reserva autenticada."""

    def obtener_factura(self, usuario_id, reserva_id):
        conexion = Database.obtener_conexion()
        cursor = conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cursor.execute(
                """
                SELECT
                    r.id, r.codigo_reserva, r.cantidad_asientos, r.total,
                    r.estado, r.fecha_reserva,
                    u.nombre_completo, u.correo, u.cedula,
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
                GROUP BY r.id, u.id, v.id
                """,
                (reserva_id, usuario_id),
            )
            factura = cursor.fetchone()
            if factura is not None:
                factura["numero_factura"] = f"FAC-{factura['id']:08d}"
            return factura
        finally:
            cursor.close()
            conexion.close()

    def generar_pdf(self, factura):
        salida = BytesIO()
        documento = SimpleDocTemplate(
            salida,
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=f"Factura {factura['numero_factura']}",
            author="FlyGo",
        )
        estilos = getSampleStyleSheet()
        elementos = [
            Paragraph("<b>FLYGO</b>", estilos["Title"]),
            Paragraph("Factura de reserva de vuelo", estilos["Heading2"]),
            Spacer(1, 8),
        ]

        cabecera = [
            ["Número", factura["numero_factura"]],
            ["Fecha de emisión", self._fecha(factura["fecha_reserva"])],
            ["Código de reserva", factura["codigo_reserva"]],
            ["Estado", factura["estado"]],
        ]
        elementos.append(self._tabla_datos(cabecera))
        elementos.extend([Spacer(1, 14), Paragraph("<b>Datos del cliente</b>", estilos["Heading3"])])
        cliente = [
            ["Nombre", factura["nombre_completo"]],
            ["Cédula", factura["cedula"] or "No registrada"],
            ["Correo", factura["correo"]],
        ]
        elementos.append(self._tabla_datos(cliente))
        elementos.extend([Spacer(1, 14), Paragraph("<b>Detalle</b>", estilos["Heading3"])])

        descripcion = (
            f"Reserva {factura['aerolinea']} - {factura['origen']} a "
            f"{factura['destino']} - {factura['fecha']} "
            f"{str(factura['hora_salida'])[:5]}"
        )
        detalle = Table(
            [
                ["Descripción", "Asientos", "Cantidad", "Total"],
                [
                    Paragraph(descripcion, estilos["BodyText"]),
                    ", ".join(factura["asientos"]) or "Sin asignar",
                    str(factura["cantidad_asientos"]),
                    self._dinero(factura["total"]),
                ],
            ],
            colWidths=[82 * mm, 38 * mm, 22 * mm, 30 * mm],
        )
        detalle.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15224B")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE3F1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elementos.extend(
            [
                detalle,
                Spacer(1, 14),
                Table(
                    [["TOTAL", self._dinero(factura["total"])]],
                    colWidths=[142 * mm, 30 * mm],
                    style=TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 12),
                        ]
                    ),
                ),
                Spacer(1, 22),
                Paragraph(
                    "Documento generado por el sistema académico FlyGo.",
                    estilos["BodyText"],
                ),
            ]
        )
        documento.build(elementos)
        salida.seek(0)
        return salida

    def generar_xml(self, factura):
        raiz = ET.Element("factura", version="1.0")
        ET.SubElement(raiz, "numero").text = factura["numero_factura"]
        ET.SubElement(raiz, "fechaEmision").text = self._fecha(factura["fecha_reserva"])
        ET.SubElement(raiz, "codigoReserva").text = factura["codigo_reserva"]
        ET.SubElement(raiz, "estado").text = factura["estado"]

        cliente = ET.SubElement(raiz, "cliente")
        ET.SubElement(cliente, "nombreCompleto").text = factura["nombre_completo"]
        ET.SubElement(cliente, "cedula").text = factura["cedula"] or ""
        ET.SubElement(cliente, "correo").text = factura["correo"]

        vuelo = ET.SubElement(raiz, "vuelo")
        ET.SubElement(vuelo, "aerolinea").text = factura["aerolinea"]
        ET.SubElement(vuelo, "origen").text = factura["origen"]
        ET.SubElement(vuelo, "destino").text = factura["destino"]
        ET.SubElement(vuelo, "fecha").text = str(factura["fecha"])
        ET.SubElement(vuelo, "horaSalida").text = str(factura["hora_salida"])[:8]
        ET.SubElement(vuelo, "horaLlegada").text = str(factura["hora_llegada"])[:8]

        detalle = ET.SubElement(raiz, "detalle")
        ET.SubElement(detalle, "cantidad").text = str(factura["cantidad_asientos"])
        asientos = ET.SubElement(detalle, "asientos")
        for numero in factura["asientos"]:
            ET.SubElement(asientos, "asiento").text = numero
        ET.SubElement(detalle, "total", moneda="USD").text = self._decimal(factura["total"])

        ET.indent(raiz, space="  ")
        contenido = ET.tostring(raiz, encoding="utf-8", xml_declaration=True)
        return BytesIO(contenido)

    @staticmethod
    def _tabla_datos(filas):
        tabla = Table(filas, colWidths=[42 * mm, 130 * mm])
        tabla.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDE3F1")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F6FB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return tabla

    @staticmethod
    def _fecha(valor):
        if isinstance(valor, datetime):
            return valor.isoformat(timespec="seconds")
        return str(valor)

    @staticmethod
    def _decimal(valor):
        return f"{Decimal(str(valor)):.2f}"

    def _dinero(self, valor):
        return f"USD {self._decimal(valor)}"
