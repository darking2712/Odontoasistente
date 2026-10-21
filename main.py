"""OdontoAsistente: API local con reservas en SQLite. Ejecutar con UN worker (las sesiones del chat viven en memoria)."""

from datetime import date, datetime
from pathlib import Path
from threading import RLock
from typing import Literal
import json
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from almacen_sqlite import AgendaSQLite, ConflictoReserva, ReservaNoEncontrada, minutos

BASE = Path(__file__).resolve().parent
NEGOCIO = json.loads((BASE / "negocio.json").read_text(encoding="utf-8-sig"))
ZONA = ZoneInfo(NEGOCIO["zona_horaria"])
if NEGOCIO["capacidad"] != 1 or NEGOCIO["paso_minutos"] <= 0:
    raise ValueError("Este ejemplo admite capacidad 1 y un paso positivo.")
if any(s["duracion_minutos"] <= 0 or s["precio_cop"] < 0 for s in NEGOCIO["servicios"].values()):
    raise ValueError("Revisar precios y duraciones del negocio.")

# Horario de cada día (0 = lunes). Los días que no aparecen están cerrados.
HORARIOS = {int(d): (minutos(h[0]), minutos(h[1])) for d, h in NEGOCIO["horarios"].items()}


class AgendaConsultorio(AgendaSQLite):
    """AgendaSQLite con dos reglas del consultorio: horario propio por día y no reservar horas que ya pasaron hoy."""

    def limites(self, fecha):
        return HORARIOS[date.fromisoformat(fecha).weekday()]

    def ya_paso(self, fecha, inicio):
        ahora = datetime.now(ZONA)
        return fecha == ahora.date().isoformat() and inicio <= ahora.hour * 60 + ahora.minute

    def validar_intervalo(self, fecha, hora, duracion, permitir_pasado=False):
        self.validar_fecha(fecha, permitir_pasado)
        apertura, cierre = self.limites(fecha)
        inicio = minutos(hora)
        if inicio < apertura or inicio + duracion > cierre:
            raise ValueError("La atención debe terminar dentro del horario de ese día")
        if (inicio - apertura) % self.paso:
            raise ValueError(f"Selecciona una hora en pasos de {self.paso} minutos")
        if not permitir_pasado and self.ya_paso(fecha, inicio):
            raise ValueError("Esa hora ya pasó. Elige una hora futura.")
        return inicio

    def disponibilidad(self, fecha, servicio, excluir=""):
        resultado = super().disponibilidad(fecha, servicio, excluir)
        _, cierre = self.limites(fecha)
        duracion = resultado["duracion_minutos"]
        resultado["horas"] = [h for h in resultado["horas"]
                              if minutos(h) + duracion <= cierre and not self.ya_paso(fecha, minutos(h))]
        return resultado


agenda = AgendaConsultorio(
    BASE / "reservas.db",
    NEGOCIO["servicios"],
    apertura=min(h[0] for h in NEGOCIO["horarios"].values()),
    cierre=max(h[1] for h in NEGOCIO["horarios"].values()),
    dias=tuple(HORARIOS),
    paso=NEGOCIO["paso_minutos"],
)

# El bloqueo solo protege las sesiones del chat (diccionario en memoria).
# Las reservas se protegen con la transacción de SQLite.
LOCK = RLock()
SESIONES: dict[str, dict] = {}
app = FastAPI(title="OdontoAsistente · API de clase", version="2.0.0",
              description="Datos ficticios. API local sin autenticación; no publicar en Internet.")


class DatosReserva(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cliente: str = Field(min_length=2, max_length=80)
    servicio: str = Field(min_length=1, max_length=40)
    fecha: date
    hora: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class CrearReserva(DatosReserva):
    confirmado: Literal[True]


class ModificarReserva(BaseModel):
    """Reagenda una reserva activa: cambia servicio, fecha y hora. El cliente no cambia."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    servicio: str = Field(min_length=1, max_length=40)
    fecha: date
    hora: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    confirmado: Literal[True]


class Extraccion(BaseModel):
    """La interpretación del LLM es entrada no confiable: se valida antes de usarla."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intencion: Literal["informacion", "reservar", "consultar", "cancelar", "continuar", "fuera"] = "continuar"
    cliente: str | None = Field(default=None, min_length=2, max_length=80)
    servicio: str | None = Field(default=None, max_length=40)
    fecha: date | None = None
    hora: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    codigo: str | None = Field(default=None, max_length=50)


class Mensaje(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=150)
    mensaje: str = Field(min_length=1, max_length=2000)
    datos: Extraccion = Field(default_factory=Extraccion)


def ejecutar(funcion, *args):
    """Llama al almacén y traduce sus errores a HTTP: 404, 409, 422 y 503."""
    try:
        return funcion(*args)
    except ReservaNoEncontrada as error:
        raise HTTPException(404, str(error)) from error
    except ConflictoReserva as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except sqlite3.Error as error:
        raise HTTPException(503, "No se pudo acceder a la base de datos. Intenta de nuevo.") from error


def servicio_valido(servicio):
    if servicio not in NEGOCIO["servicios"]:
        raise HTTPException(422, "Servicio desconocido. Opciones: " + ", ".join(NEGOCIO["servicios"]))
    return NEGOCIO["servicios"][servicio]


def con_precio(reserva):
    """La tabla guarda la duración; el precio se toma del catálogo actual."""
    precio = NEGOCIO["servicios"].get(reserva["servicio"], {}).get("precio_cop")
    return {**reserva, "precio_cop": precio}


def horas_libres(fecha, servicio):
    servicio_valido(servicio)
    if fecha.weekday() not in HORARIOS:
        return []
    return ejecutar(agenda.disponibilidad, fecha.isoformat(), servicio)["horas"]


@app.get("/servicios")
def servicios():
    return NEGOCIO


@app.get("/disponibilidad")
def disponibilidad(fecha: date, servicio: str):
    return {"fecha": fecha.isoformat(), "servicio": servicio,
            "horarios": horas_libres(fecha, servicio)}


@app.get("/reservas")
def listar():
    return [con_precio(r) for r in ejecutar(agenda.listar)]


@app.post("/reservas", status_code=201)
def crear(datos: CrearReserva):
    servicio_valido(datos.servicio)
    return con_precio(ejecutar(agenda.crear, datos.cliente, datos.servicio,
                               datos.fecha.isoformat(), datos.hora))


@app.put("/reservas/{codigo}")
def modificar(codigo: str, datos: ModificarReserva):
    servicio_valido(datos.servicio)
    return con_precio(ejecutar(agenda.modificar, codigo.strip().upper(), datos.servicio,
                               datos.fecha.isoformat(), datos.hora))


@app.get("/reservas/{codigo}")
def consultar(codigo: str):
    return con_precio(ejecutar(agenda.consultar, codigo.strip().upper()))


@app.delete("/reservas/{codigo}")
def cancelar(codigo: str, confirmado: bool = Query(False)):
    if not confirmado:
        raise HTTPException(422, "Se requiere confirmación para cancelar.")
    return con_precio(ejecutar(agenda.cancelar, codigo.strip().upper()))


def resumen(r):
    return f"{r['cliente']}: {r['servicio']}, {r['fecha']} a las {r['hora']}"


def pesos(valor):
    return f"${valor:,}".replace(",", ".") + " COP"


def responder(estado, texto):
    return {"respuesta": texto, "estado_sesion": estado.copy()}


@app.post("/chat")
def chat(entrada: Mensaje):
    """Puente de Flowise. El estado y la confirmación se controlan aquí, sin agentes."""
    with LOCK:
        estado = SESIONES.setdefault(entrada.session_id, {})
        mensaje = entrada.mensaje.strip().casefold()
        if mensaje == "/reset":
            estado.clear()
            return responder(estado, "Solicitud reiniciada. Las reservas registradas se conservan.")
        if mensaje in {"no", "abortar"}:
            estado.clear()
            return responder(estado, "Solicitud descartada. No se cambió ninguna reserva.")
        try:
            # Solo la palabra exacta confirma el resumen guardado: el LLM no puede autorizarlo.
            if mensaje == "confirmar":
                pendiente = estado.get("pendiente")
                if not pendiente:
                    return responder(estado, "No hay un resumen pendiente. Primero completa la solicitud.")
                if pendiente["accion"] == "crear":
                    resultado = crear(CrearReserva(**pendiente["datos"], confirmado=True))
                    texto = "Reserva registrada. " + resumen(resultado)
                else:
                    resultado = cancelar(pendiente["codigo"], confirmado=True)
                    texto = "Reserva cancelada. " + resumen(resultado)
                estado.clear()
                estado["ultimo_codigo"] = resultado["codigo"]
                return responder(estado, texto + ". Código: " + resultado["codigo"])

            datos = entrada.datos.model_dump(mode="json", exclude_none=True)
            intencion = datos.pop("intencion")
            if intencion == "fuera":
                return responder(estado, "Puedo ayudarte con información y reservas de " + NEGOCIO["nombre"] + ".")
            if intencion == "informacion":
                catalogo = "; ".join(f"{s['nombre']}: {pesos(s['precio_cop'])}, {s['duracion_minutos']} minutos"
                                     for s in NEGOCIO["servicios"].values())
                dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                horarios = "; ".join(f"{dias[int(dia)]}: {horas[0]}–{horas[1]}" for dia, horas in NEGOCIO["horarios"].items())
                return responder(estado, catalogo + ". " + NEGOCIO["ubicacion"] + ". Horarios: "
                                 + horarios + ". " + NEGOCIO["condiciones"]
                                 + " Si estabas reservando, conservé tus datos.")
            if intencion in {"reservar", "consultar", "cancelar"}:
                if estado.get("intencion") != intencion:
                    estado.clear()
                estado["intencion"] = intencion
            if not estado.get("intencion"):
                estado["intencion"] = "reservar" if datos else "inicio"
            if estado["intencion"] == "inicio":
                estado.clear()
                return responder(estado, "Hola. Puedo informar, reservar, consultar o cancelar. ¿Qué necesitas?")
            if any(estado.get(k) != v for k, v in datos.items()):
                estado.pop("pendiente", None)
            estado.update(datos)
            accion = estado["intencion"]
            if accion in {"consultar", "cancelar"}:
                if not estado.get("codigo"):
                    return responder(estado, "Escribe el código de la reserva, por ejemplo 1A2B3C4D.")
                r = consultar(estado["codigo"])
                if accion == "consultar":
                    return responder(estado, resumen(r) + ". Estado: " + r["estado"] + ". Código: " + r["codigo"])
                if r["estado"] == "cancelada":
                    return responder(estado, "Esta reserva ya está cancelada.")
                estado["pendiente"] = {"accion": "cancelar", "codigo": r["codigo"]}
                return responder(estado, "Vas a cancelar: " + resumen(r) + ". Escribe CONFIRMAR o ABORTAR.")

            if not estado.get("servicio"):
                opciones = ", ".join(s["nombre"] for s in NEGOCIO["servicios"].values())
                return responder(estado, "¿Qué servicio necesitas? Opciones: " + opciones + ".")
            servicio_valido(estado["servicio"])
            if not estado.get("fecha"):
                return responder(estado, "Indica la fecha completa en formato AAAA-MM-DD.")
            fecha = date.fromisoformat(estado["fecha"])
            libres = horas_libres(fecha, estado["servicio"])
            if not libres:
                estado.pop("pendiente", None)
                return responder(estado, "No hay horarios disponibles para esa fecha. Indica otra fecha.")
            if not estado.get("hora") or estado["hora"] not in libres:
                estado.pop("pendiente", None)
                return responder(estado, "Elige una hora disponible: " + ", ".join(libres))
            if not estado.get("cliente"):
                return responder(estado, "¿A nombre de quién preparo la reserva?")
            solicitud = DatosReserva(**{k: estado[k] for k in DatosReserva.model_fields}).model_dump(mode="json")
            estado["pendiente"] = {"accion": "crear", "datos": solicitud}
            precio = servicio_valido(solicitud["servicio"])["precio_cop"]
            return responder(estado, "Solicitud: " + resumen(solicitud) + f". Precio: {pesos(precio)}. "
                             "Escribe CONFIRMAR para registrar o ABORTAR. Aún no se ha guardado.")
        except HTTPException as exc:
            estado.pop("pendiente", None)
            return JSONResponse(status_code=exc.status_code, content=responder(estado, exc.detail))
        except (ValidationError, ValueError):
            estado.pop("pendiente", None)
            return JSONResponse(status_code=422, content=responder(estado, "Revisa los datos: fecha AAAA-MM-DD y hora HH:MM."))
