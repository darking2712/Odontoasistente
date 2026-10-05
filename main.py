"""Demo local de un solo negocio. Ejecutar con UN worker; usar datos ficticios."""

import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BASE = Path(__file__).resolve().parent
ARCHIVO = BASE / "reservas.json"
NEGOCIO = json.loads((BASE / "negocio.json").read_text(encoding="utf-8-sig"))
ZONA = ZoneInfo(NEGOCIO["zona_horaria"])
if NEGOCIO["capacidad"] != 1 or NEGOCIO["paso_minutos"] <= 0:
    raise ValueError("Este ejemplo admite capacidad 1 y un paso positivo.")
if any(s["duracion_minutos"] <= 0 or s["precio_cop"] < 0 for s in NEGOCIO["servicios"].values()):
    raise ValueError("Revisar precios y duraciones del negocio.")

# ponytail: bloqueo global de un solo proceso; migrar a transacciones SQLite para varios workers.
LOCK = RLock()
SESIONES: dict[str, dict] = {}
app = FastAPI(title="Punto Norte · API de clase", version="1.0.0",
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


class Registro(DatosReserva):
    codigo: str
    estado: Literal["activa", "cancelada"]
    precio_cop: int
    duracion_minutos: int = Field(gt=0)
    creada_en: str
    cancelada_en: str | None = None
    modificada_en: str | None = None


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


def leer():
    try:
        contenido = json.loads(ARCHIVO.read_text(encoding="utf-8-sig"))
        if not isinstance(contenido, list):
            raise ValueError("Se esperaba una lista")
        return [Registro.model_validate(r).model_dump(mode="json") for r in contenido]
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "No se pudo leer reservas.json. Revisar el archivo; no se sobrescribió.") from exc


def guardar(registros):
    temporal = ARCHIVO.with_suffix(".tmp")
    try:
        with temporal.open("w", encoding="utf-8") as archivo:
            json.dump(registros, archivo, ensure_ascii=False, indent=2)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ARCHIVO)
    except OSError as exc:
        raise HTTPException(503, "No se pudo guardar la operación. No se confirmó su registro.") from exc


def servicio_valido(servicio):
    if servicio not in NEGOCIO["servicios"]:
        raise HTTPException(422, "Servicio desconocido. Opciones: " + ", ".join(NEGOCIO["servicios"]))
    return NEGOCIO["servicios"][servicio]


def horarios_libres(fecha, servicio, registros):
    duracion = servicio_valido(servicio)["duracion_minutos"]
    ahora = datetime.now(ZONA)
    if fecha < ahora.date():
        raise HTTPException(422, "La fecha ya pasó. Elige una fecha futura.")
    horario = NEGOCIO["horarios"].get(str(fecha.weekday()))
    if not horario:
        return []
    inicio = datetime.combine(fecha, time.fromisoformat(horario[0]), ZONA)
    cierre = datetime.combine(fecha, time.fromisoformat(horario[1]), ZONA)
    ocupados = []
    for r in registros:
        if r["fecha"] == fecha.isoformat() and r["estado"] == "activa":
            desde = datetime.combine(fecha, time.fromisoformat(r["hora"]), ZONA)
            ocupados.append((desde, desde + timedelta(minutes=r["duracion_minutos"])))
    libres = []
    while inicio + timedelta(minutes=duracion) <= cierre:
        fin = inicio + timedelta(minutes=duracion)
        if inicio > ahora and not any(inicio < hasta and fin > desde for desde, hasta in ocupados):
            libres.append(inicio.strftime("%H:%M"))
        inicio += timedelta(minutes=NEGOCIO["paso_minutos"])
    return libres


@app.get("/servicios")
def servicios():
    return NEGOCIO


@app.get("/disponibilidad")
def disponibilidad(fecha: date, servicio: str):
    with LOCK:
        return {"fecha": fecha.isoformat(), "servicio": servicio,
                "horarios": horarios_libres(fecha, servicio, leer())}


@app.post("/reservas", status_code=201)
def crear(datos: CrearReserva):
    with LOCK:
        registros = leer()
        if datos.hora not in horarios_libres(datos.fecha, datos.servicio, registros):
            raise HTTPException(409, "Horario no disponible. La reserva no se registró.")
        servicio = servicio_valido(datos.servicio)
        registro = Registro(**datos.model_dump(exclude={"confirmado"}),
                            codigo="OA-" + uuid4().hex[:12].upper(), estado="activa",
                            precio_cop=servicio["precio_cop"], duracion_minutos=servicio["duracion_minutos"],
                            creada_en=datetime.now(ZONA).isoformat()).model_dump(mode="json")
        registros.append(registro)
        guardar(registros)
        return registro


@app.put("/reservas/{codigo}")
def modificar(codigo: str, datos: ModificarReserva):
    with LOCK:
        registros = leer()
        for r in registros:
            if r["codigo"] != codigo.strip().upper():
                continue
            if r["estado"] != "activa":
                raise HTTPException(409, "Solo se pueden modificar reservas activas.")
            servicio = servicio_valido(datos.servicio)
            # Se calcula la disponibilidad sin contar la reserva que se está modificando,
            # para que no choque consigo misma al conservar la misma hora.
            otros = [x for x in registros if x["codigo"] != r["codigo"]]
            if datos.hora not in horarios_libres(datos.fecha, datos.servicio, otros):
                raise HTTPException(409, "Horario no disponible. La reserva no se modificó.")
            r.update(servicio=datos.servicio, fecha=datos.fecha.isoformat(), hora=datos.hora,
                      precio_cop=servicio["precio_cop"], duracion_minutos=servicio["duracion_minutos"],
                      modificada_en=datetime.now(ZONA).isoformat())
            guardar(registros)
            return r
    raise HTTPException(404, "No existe una reserva con ese código.")


@app.get("/reservas/{codigo}")
def consultar(codigo: str):
    with LOCK:
        for r in leer():
            if r["codigo"] == codigo.strip().upper():
                return r
    raise HTTPException(404, "No existe una reserva con ese código.")


@app.delete("/reservas/{codigo}")
def cancelar(codigo: str, confirmado: bool = Query(False)):
    if not confirmado:
        raise HTTPException(422, "Se requiere confirmación para cancelar.")
    with LOCK:
        registros = leer()
        for r in registros:
            if r["codigo"] == codigo.strip().upper():
                if r["estado"] == "activa":
                    r.update(estado="cancelada", cancelada_en=datetime.now(ZONA).isoformat())
                    guardar(registros)
                return r
    raise HTTPException(404, "No existe una reserva con ese código.")


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
                    return responder(estado, "Escribe el código de la reserva, por ejemplo PN-...")
                r = consultar(estado["codigo"])
                if accion == "consultar":
                    return responder(estado, resumen(r) + ". Estado: " + r["estado"] + ". Código: " + r["codigo"])
                if r["estado"] == "cancelada":
                    return responder(estado, "Esta reserva ya está cancelada.")
                estado["pendiente"] = {"accion": "cancelar", "codigo": r["codigo"]}
                return responder(estado, "Vas a cancelar: " + resumen(r) + ". Escribe CONFIRMAR o ABORTAR.")

            if not estado.get("servicio"):
                return responder(estado, "¿Qué servicio necesitas: corte o barba?")
            servicio_valido(estado["servicio"])
            if not estado.get("fecha"):
                return responder(estado, "Indica la fecha completa en formato AAAA-MM-DD.")
            fecha = date.fromisoformat(estado["fecha"])
            libres = horarios_libres(fecha, estado["servicio"], leer())
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
