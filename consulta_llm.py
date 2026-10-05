"""Lógica del chatbot OdontoAsistente: Groq interpreta y la FastAPI ejecuta.

En esta clase se usa desde la terminal. Más adelante Gradio podrá llamar
interpretar() y ejecutar() sin cambiar la lógica del negocio.

Adaptado a la FastAPI de OdontoAsistente (main.py):
  GET    /servicios
  GET    /disponibilidad?fecha=AAAA-MM-DD&servicio=clave
  POST   /reservas                        (cuerpo con "confirmado": true)
  GET    /reservas/{codigo}
  DELETE /reservas/{codigo}?confirmado=true
Esa API no tiene PUT, así que aquí no se modifica: se consulta, se crea y se cancela.
"""

import json
import os
from datetime import datetime
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

API_BASE = os.getenv("CHATBOT_API_URL", "http://127.0.0.1:8011").rstrip("/")
RUTAS = {
    "servicios": "/servicios",
    "disponibilidad": "/disponibilidad",
    "reservas": "/reservas",
}
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ACCIONES = {"servicios", "disponibilidad", "crear", "modificar", "consultar", "cancelar", "fuera_de_alcance"}
CAMPOS = ("accion", "cliente", "servicio", "fecha", "hora", "codigo")
REQUERIDOS = {
    "disponibilidad": ("servicio", "fecha"),
    "crear": ("cliente", "servicio", "fecha", "hora"),
    "modificar": ("codigo", "servicio", "fecha", "hora"),
    "consultar": ("codigo",),
    "cancelar": ("codigo",),
}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
INSTRUCCIONES = """
Eres el intérprete de un consultorio odontológico. Identifica qué quiere hacer
la persona. Devuelve únicamente un objeto JSON con estas claves: accion,
cliente, servicio, fecha, hora, codigo.
Las acciones posibles son: servicios, disponibilidad, crear, modificar,
consultar, cancelar, fuera_de_alcance.
- servicios: quiere conocer los servicios, precios u horarios.
- disponibilidad: quiere saber qué horas hay libres para un servicio y una fecha.
- crear: quiere agendar una cita nueva.
- modificar: quiere cambiar el servicio, la fecha o la hora de una cita que ya existe;
  siempre necesita el código de esa reserva.
- consultar: quiere ver una reserva con su código.
- cancelar: quiere cancelar una reserva con su código.
- fuera_de_alcance: cualquier otra cosa (diagnósticos, tratamientos, pagos, etc.).
En servicio usa exactamente una de estas claves: valoracion, limpieza,
blanqueamiento, ortodoncia, extraccion. Si no corresponde a ninguna, usa cadena vacía.
Usa fecha AAAA-MM-DD y hora HH:MM en formato de 24 horas. Hoy es {dia} {hoy}.
El código de una reserva tiene la forma OA-XXXXXXXXXXXX.
Si un dato no aparece en la pregunta, usa una cadena vacía; no lo inventes.
No digas que hiciste una reserva: solo identifica la intención.
"""


def ahora():
    try:
        return datetime.now(ZoneInfo("America/Bogota"))
    except ZoneInfoNotFoundError:
        return datetime.now()


def instrucciones():
    momento = ahora()
    return INSTRUCCIONES.format(dia=DIAS[momento.weekday()], hoy=momento.strftime("%Y-%m-%d"))


def peticion_json(url, metodo="GET", datos=None, headers=None):
    cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8") if datos is not None else None
    # Groq (Cloudflare) rechaza con 403 el User-Agent por defecto de urllib.
    encabezados = {"User-Agent": "Mozilla/5.0 (OdontoAsistente)", "Accept": "application/json"}
    if cuerpo is not None:
        encabezados["Content-Type"] = "application/json"
    encabezados.update(headers or {})
    solicitud = Request(url, data=cuerpo, headers=encabezados, method=metodo)
    with urlopen(solicitud, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def interpretar(pregunta, clave, modelo):
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": instrucciones()},
            {"role": "user", "content": pregunta},
        ],
        "stream": False,
    }
    respuesta = peticion_json(
        GROQ_URL, "POST", payload,
        {"Authorization": f"Bearer {clave}"},
    )
    texto = respuesta["choices"][0]["message"]["content"] or ""
    # Algunos modelos rodean el JSON con texto o con ```; nos quedamos con el objeto.
    plan = json.loads(texto[texto.find("{"):texto.rfind("}") + 1])
    if not isinstance(plan, dict) or plan.get("accion") not in ACCIONES:
        raise ValueError("Groq no devolvió una acción válida")
    plan = {campo: str(plan.get(campo) or "").strip() for campo in CAMPOS}
    plan["servicio"] = plan["servicio"].lower()
    plan["codigo"] = plan["codigo"].upper()
    return plan


def ejecutar(plan, confirmar=False, api_base=API_BASE):
    accion = plan["accion"]
    if accion not in ACCIONES:
        raise ValueError("Acción no permitida")
    if accion == "fuera_de_alcance":
        return {"tipo": "mensaje", "mensaje": "Puedo ayudar con servicios, disponibilidad y reservas."}

    faltan = [campo for campo in REQUERIDOS.get(accion, ()) if not plan.get(campo)]
    if faltan:
        return {"tipo": "faltan_datos", "mensaje": "Necesito: " + ", ".join(faltan), "plan": plan}

    if accion in {"crear", "modificar", "cancelar"} and not confirmar:
        resumen = ", ".join(f"{campo}={plan[campo]}" for campo in REQUERIDOS[accion])
        return {"tipo": "confirmacion", "mensaje": f"Voy a {accion} la reserva: {resumen}. ¿Confirmas?", "plan": plan}

    base = api_base.rstrip("/")
    reservas = RUTAS["reservas"]
    if accion == "servicios":
        datos = peticion_json(base + RUTAS["servicios"])
    elif accion == "disponibilidad":
        parametros = urlencode({"fecha": plan["fecha"], "servicio": plan["servicio"]})
        datos = peticion_json(base + RUTAS["disponibilidad"] + "?" + parametros)
    elif accion == "crear":
        cuerpo = {campo: plan[campo] for campo in ("cliente", "servicio", "fecha", "hora")}
        cuerpo["confirmado"] = True
        datos = peticion_json(base + reservas, "POST", cuerpo)
    elif accion == "modificar":
        cuerpo = {campo: plan[campo] for campo in ("servicio", "fecha", "hora")}
        cuerpo["confirmado"] = True
        datos = peticion_json(base + reservas + "/" + quote(plan["codigo"], safe=""), "PUT", cuerpo)
    elif accion == "consultar":
        datos = peticion_json(base + reservas + "/" + quote(plan["codigo"], safe=""))
    else:
        datos = peticion_json(base + reservas + "/" + quote(plan["codigo"], safe="") + "?confirmado=true", "DELETE")
    return {"tipo": "resultado", "accion": accion, "datos": datos}


def detalle_error(error):
    """Lee el mensaje que devolvió Groq o la FastAPI para mostrarlo en pantalla."""
    try:
        texto = error.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    try:
        cuerpo = json.loads(texto)
    except ValueError:
        return texto.strip()[:200]  # respuesta que no es JSON (por ejemplo, un bloqueo)
    if not isinstance(cuerpo, dict):
        return ""
    mensaje = cuerpo.get("detail") or cuerpo.get("error") or ""
    if isinstance(mensaje, dict):
        mensaje = mensaje.get("message", "")
    return mensaje if isinstance(mensaje, str) else json.dumps(mensaje, ensure_ascii=False)


def main():
    clave = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq: ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not clave or not modelo:
        print("Necesito la API key y el ID del modelo.")
        return
    print("Escribe una solicitud. Para terminar, escribe SALIR.")
    while True:
        pregunta = input("\nTú: ").strip()
        if pregunta.casefold() == "salir":
            break
        if not pregunta:
            continue
        try:
            plan = interpretar(pregunta, clave, modelo)
            print("Plan:", json.dumps(plan, ensure_ascii=False))
            resultado = ejecutar(plan)
            print("Chatbot:", resultado.get("mensaje") or json.dumps(resultado["datos"], ensure_ascii=False, indent=2))
            if resultado["tipo"] == "confirmacion" and input("Confirmar (s/n): ").strip().casefold() == "s":
                resultado = ejecutar(plan, confirmar=True)
                print("FastAPI:", json.dumps(resultado["datos"], ensure_ascii=False, indent=2))
        except HTTPError as error:
            print(f"Error HTTP {error.code}: {detalle_error(error)}".rstrip(": "))
            print("Revisa la respuesta de Groq o de la FastAPI.")
        except (URLError, TimeoutError):
            print("No pude conectar con Groq o con la FastAPI. Revisa ambos servicios.")
        except (ValueError, KeyError, IndexError, TypeError):
            print("No pude interpretar la respuesta. Revisa el formato JSON y los datos solicitados.")


if __name__ == "__main__":
    main()
