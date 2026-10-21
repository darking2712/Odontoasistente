"""Prueba reproducible sin Groq ni Flowise. Usa una base SQLite temporal: no toca reservas.db.

Ejecutar desde la carpeta del proyecto:  python probar_demo.py
Cada comprobación imprime [OK] o detiene la prueba con el nombre de la que falló.
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def verificar(nombre, condicion, detalle=""):
    if not condicion:
        raise AssertionError(f"FALLÓ: {nombre}. {detalle}".strip())
    print(f"[OK] {nombre}")


def seccion(titulo):
    print(f"\n== {titulo} ==")


def agenda_temporal(ruta):
    """Misma configuración que main.agenda, pero sobre otro archivo."""
    return main.AgendaConsultorio(
        ruta, main.NEGOCIO["servicios"],
        apertura=min(h[0] for h in main.NEGOCIO["horarios"].values()),
        cierre=max(h[1] for h in main.NEGOCIO["horarios"].values()),
        dias=tuple(main.HORARIOS), paso=main.NEGOCIO["paso_minutos"],
    )


def filas(ruta):
    """Lee las filas directamente de SQLite, sin pasar por la API."""
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    try:
        return {f["codigo"]: dict(f) for f in con.execute("SELECT * FROM reservas")}
    finally:
        con.close()


def dia_habil(desde):
    while desde.weekday() > 4:  # lunes a viernes
        desde += timedelta(days=1)
    return desde


def probar():
    with TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "reservas_prueba.db"
        original = main.agenda
        main.agenda = agenda_temporal(ruta)
        main.SESIONES.clear()
        try:
            with TestClient(main.app) as api:
                hoy = datetime.now(main.ZONA).date()
                fecha = dia_habil(hoy + timedelta(days=2))
                dia = fecha.isoformat()
                dia2 = dia_habil(fecha + timedelta(days=1)).isoformat()
                datos = dict(cliente="Laura", servicio="valoracion", fecha=dia, hora="09:00", confirmado=True)

                def libres(servicio, d=dia):
                    return api.get("/disponibilidad", params={"fecha": d, "servicio": servicio}).json()["horarios"]

                seccion("1. Validaciones de la API")
                verificar("GET /servicios responde 200", api.get("/servicios").status_code == 200)
                verificar("09:00 aparece libre en un día sin reservas", "09:00" in libres("valoracion"))
                verificar("sin confirmado=true se rechaza (422)", api.post("/reservas", json={**datos, "confirmado": False}).status_code == 422)
                verificar("hora 25:00 se rechaza (422)", api.post("/reservas", json={**datos, "hora": "25:00"}).status_code == 422)
                verificar("servicio inventado se rechaza (422)", api.post("/reservas", json={**datos, "servicio": "inventado"}).status_code == 422)
                verificar("atención que termina después del cierre (18:00 + 30 min) se rechaza (422)", api.post("/reservas", json={**datos, "hora": "18:00"}).status_code == 422)
                verificar("hora fuera del paso de 30 min (09:15) se rechaza (422)", api.post("/reservas", json={**datos, "hora": "09:15"}).status_code == 422)
                verificar("fecha pasada se rechaza (422)", api.post("/reservas", json={**datos, "fecha": "2000-01-01"}).status_code == 422)
                domingo = fecha + timedelta(days=(6 - fecha.weekday()))
                verificar("domingo cerrado: sin horarios", libres("valoracion", domingo.isoformat()) == [])
                sabado = fecha + timedelta(days=(5 - fecha.weekday()))
                verificar("sábado cierra a las 13:00: última valoración 12:30", libres("valoracion", sabado.isoformat())[-1] == "12:30")
                verificar("hasta aquí no se guardó ninguna fila", len(filas(ruta)) == 0)

                seccion("2. Concurrencia: dos peticiones por el mismo horario")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    respuestas = list(pool.map(lambda _: api.post("/reservas", json=datos), range(2)))
                verificar("una se registra (201) y la otra se rechaza (409)", sorted(r.status_code for r in respuestas) == [201, 409])
                reserva_a = next(r.json() for r in respuestas if r.status_code == 201)
                a = reserva_a["codigo"]
                verificar("SQLite tiene exactamente 1 fila activa", [f["estado"] for f in filas(ruta).values()] == ["activa"])

                seccion("3. Persistencia al reiniciar la API")
                main.SESIONES.clear()
                main.agenda = agenda_temporal(ruta)  # objeto nuevo sobre el mismo archivo = API reiniciada
                verificar("la reserva sigue activa tras reiniciar", api.get("/reservas/" + a).json()["estado"] == "activa")
                verificar("consultar un código inexistente da 404", api.get("/reservas/INEXISTENTE").status_code == 404)

                seccion("4. Cruce de intervalos (reserva activa 09:00-09:30)")
                lim = libres("limpieza")  # 45 min
                verificar("limpieza 08:30 (termina 09:15) no está libre", "08:30" not in lim)
                verificar("limpieza 09:00 no está libre", "09:00" not in lim)
                verificar("limpieza 08:00 (termina 08:45) sí está libre", "08:00" in lim)
                verificar("limpieza 09:30 (empieza al terminar la otra) sí está libre", "09:30" in lim)
                verificar("POST limpieza 08:30 se rechaza por cruce (409)", api.post("/reservas", json={**datos, "servicio": "limpieza", "hora": "08:30"}).status_code == 409)
                verificar("POST limpieza 09:00 se rechaza por cruce (409)", api.post("/reservas", json={**datos, "servicio": "limpieza", "hora": "09:00"}).status_code == 409)

                seccion("5. Modificar")
                b = api.post("/reservas", json={**datos, "cliente": "Pedro", "hora": "10:00"}).json()["codigo"]
                cuerpo = dict(servicio="valoracion", fecha=dia, hora="10:00", confirmado=True)
                verificar("PUT sin confirmado=true se rechaza (422)", api.put("/reservas/" + a, json={**cuerpo, "confirmado": False}).status_code == 422)
                verificar("PUT sobre código inexistente da 404", api.put("/reservas/INEXISTENTE", json=cuerpo).status_code == 404)
                verificar("PUT a un horario ocupado por otra reserva da 409", api.put("/reservas/" + a, json=cuerpo).status_code == 409)
                r = api.put("/reservas/" + a, json={**cuerpo, "servicio": "limpieza", "hora": "09:00"})
                verificar("PUT puede solaparse con su propio horario anterior (200, dura 45 min)", r.status_code == 200 and r.json()["duracion_minutos"] == 45)
                verificar("PUT que invade la reserva de Pedro (09:30 + 45 min) da 409", api.put("/reservas/" + a, json={**cuerpo, "servicio": "limpieza", "hora": "09:30"}).status_code == 409)
                r = api.put("/reservas/" + a, json={**cuerpo, "hora": "11:00"})
                verificar("PUT a un horario libre (11:00) responde 200", r.status_code == 200 and r.json()["hora"] == "11:00")
                fila = filas(ruta)[a]
                verificar("SQLite refleja el cambio (valoracion, 11:00, 30 min)", (fila["servicio"], fila["hora"], fila["duracion_minutos"]) == ("valoracion", "11:00", 30))
                verificar("el horario anterior (09:00) quedó libre", "09:00" in libres("valoracion"))

                seccion("6. Cancelar")
                verificar("DELETE sin confirmado=true se rechaza (422)", api.delete("/reservas/" + a).status_code == 422)
                verificar("DELETE confirmado cancela la reserva", api.delete("/reservas/" + a, params={"confirmado": True}).json()["estado"] == "cancelada")
                verificar("cancelar dos veces da 409", api.delete("/reservas/" + a, params={"confirmado": True}).status_code == 409)
                verificar("modificar una reserva cancelada da 409", api.put("/reservas/" + a, json=cuerpo).status_code == 409)
                verificar("la cancelación libera el horario (11:00)", "11:00" in libres("valoracion"))
                verificar("la fila cancelada se conserva en SQLite", filas(ruta)[a]["estado"] == "cancelada" and filas(ruta)[b]["estado"] == "activa")

                seccion("7. Chat: varios turnos, confirmación, dos sesiones y reinicio")

                def chat(texto, extraccion=None, sesion="grupo-1"):
                    return api.post("/chat", json={"session_id": sesion, "mensaje": texto, "datos": extraccion or {}})

                ext = {k: v for k, v in datos.items() if k != "confirmado"}
                ext.update(fecha=dia2, intencion="reservar")
                antes = len(filas(ruta))
                r = chat("Quiero reservar", ext).json()
                verificar("el chat arma el resumen pendiente (09:00)", r["estado_sesion"]["pendiente"]["datos"]["hora"] == "09:00")
                verificar("el resumen aún no guarda nada en SQLite", len(filas(ruta)) == antes)
                verificar("otra sesión no puede confirmar el resumen ajeno", "No hay un resumen" in chat("CONFIRMAR", sesion="grupo-2").json()["respuesta"])
                r = chat("Mejor a las 10:00", {"intencion": "continuar", "hora": "10:00"}).json()
                verificar("la corrección conserva los demás datos y cambia la hora", r["estado_sesion"]["pendiente"]["datos"] == {**r["estado_sesion"]["pendiente"]["datos"], "cliente": "Laura", "hora": "10:00"})
                r = chat("Reservar", {**ext, "cliente": "Marta"}, sesion="grupo-2").json()
                verificar("dos sesiones guardan datos distintos", r["estado_sesion"]["pendiente"]["datos"]["cliente"] == "Marta" and main.SESIONES["grupo-1"]["pendiente"]["datos"]["cliente"] == "Laura")
                chat("/reset", sesion="grupo-2")
                verificar("/reset limpia solo la sesión indicada", main.SESIONES["grupo-2"] == {} and "pendiente" in main.SESIONES["grupo-1"])
                verificar("preguntar un precio no pierde el resumen pendiente", "pendiente" in chat("Cuánto cuesta", {"intencion": "informacion"}).json()["estado_sesion"])
                verificar("un 'Sí' no confirma: solo CONFIRMAR autoriza", "pendiente" in chat("Sí").json()["estado_sesion"])
                r = chat("CONFIRMAR").json()
                verificar("CONFIRMAR registra la reserva", "Reserva registrada" in r["respuesta"])
                c = r["estado_sesion"]["ultimo_codigo"]
                verificar("la reserva quedó en SQLite a las 10:00", filas(ruta)[c]["hora"] == "10:00" and len(filas(ruta)) == antes + 1)
                verificar("un segundo CONFIRMAR no duplica la reserva", "No hay un resumen" in chat("CONFIRMAR").json()["respuesta"] and len(filas(ruta)) == antes + 1)
                chat("/reset")
                verificar("/reset conserva las reservas ya registradas", filas(ruta)[c]["estado"] == "activa")
                chat("Cancelar " + c, {"intencion": "cancelar", "codigo": c})
                verificar("pedir cancelar no cancela hasta confirmar", filas(ruta)[c]["estado"] == "activa")
                verificar("CONFIRMAR cancela la reserva", "Reserva cancelada" in chat("CONFIRMAR").json()["respuesta"] and filas(ruta)[c]["estado"] == "cancelada")
                verificar("datos con 'confirmado' inyectado se rechazan (422)", chat("Datos maliciosos", {"intencion": "continuar", "confirmado": True}).status_code == 422)
                chat("Reservar", ext)  # resumen 09:00 en dia2
                verificar("POST directo toma el horario antes de confirmar", api.post("/reservas", json={**datos, "fecha": dia2}).status_code == 201)
                verificar("CONFIRMAR con el horario ya ocupado da 409", chat("CONFIRMAR").status_code == 409)
                verificar("tras el 409 el resumen pendiente se descarta", "pendiente" not in main.SESIONES["grupo-1"])

                seccion("8. Errores de almacenamiento")
                antes = filas(ruta)
                nuevo = {**datos, "fecha": dia2, "hora": "11:00"}
                with patch.object(main.agenda, "conexion", side_effect=sqlite3.OperationalError("Prueba de disco")):
                    verificar("fallo de SQLite al crear informa 503", api.post("/reservas", json=nuevo).status_code == 503)
                    verificar("fallo de SQLite al listar informa 503", api.get("/reservas").status_code == 503)
                verificar("tras el fallo no cambió ninguna fila", filas(ruta) == antes)
                verificar("al volver el almacén se puede continuar (201)", api.post("/reservas", json=nuevo).status_code == 201)

                print("\nOK: validaciones, concurrencia, persistencia, cruces, modificación, cancelación, chat y errores.")
        finally:
            main.agenda = original
            main.SESIONES.clear()


if __name__ == "__main__":
    probar()
