"""Clase 07: historial de conversación sobre la lógica de la clase 06.

Coloca este archivo junto a consulta_llm.py. Más adelante Gradio podrá usar
nuevo_historial() y procesar_turno() sin copiar la lógica del negocio.
"""

import json
import os
from getpass import getpass
from urllib.error import HTTPError, URLError

from consulta_llm import ACCIONES, CAMPOS, GROQ_URL, detalle_error, ejecutar, instrucciones, peticion_json


def nuevo_historial():
    # Se reutiliza exactamente el mismo prompt que usa consulta_llm.py (mismas
    # claves de servicio, misma fecha de hoy, mismas acciones permitidas), para
    # que interpretar en un solo turno o en varios se comporte igual.
    return [{"role": "system", "content": instrucciones()}]


def interpretar_turno(pregunta, historial, clave, modelo):
    mensajes = historial + [{"role": "user", "content": pregunta}]
    payload = {"model": modelo, "messages": mensajes, "stream": False}
    respuesta = peticion_json(
        GROQ_URL, "POST", payload, {"Authorization": f"Bearer {clave}"}
    )
    texto = respuesta["choices"][0]["message"]["content"] or ""
    # Igual que en consulta_llm.interpretar(): nos quedamos con el objeto JSON,
    # por si el modelo agrega texto o ``` alrededor.
    plan = json.loads(texto[texto.find("{"):texto.rfind("}") + 1])
    if not isinstance(plan, dict) or plan.get("accion") not in ACCIONES:
        raise ValueError("Groq no devolvió una acción válida")
    plan = {campo: str(plan.get(campo) or "").strip() for campo in CAMPOS}
    plan["servicio"] = plan["servicio"].lower()
    plan["codigo"] = plan["codigo"].upper()
    return plan, mensajes


def procesar_turno(pregunta, historial, clave, modelo):
    plan, mensajes = interpretar_turno(pregunta, historial, clave, modelo)
    resultado = ejecutar(plan)
    resumen = {"plan": plan, "respuesta": resultado.get("mensaje", resultado.get("datos"))}
    actualizado = mensajes + [
        {"role": "assistant", "content": json.dumps(resumen, ensure_ascii=False)}
    ]
    return resultado, actualizado, plan


def main():
    clave = os.getenv("GROQ_API_KEY", "").strip() or getpass("API key de Groq: ").strip()
    modelo = os.getenv("GROQ_MODEL", "").strip() or input("ID del modelo de Groq: ").strip()
    if not clave or not modelo:
        print("Necesito la API key y el ID del modelo.")
        return
    historial = nuevo_historial()
    print("Escribe tu solicitud. REINICIAR borra el historial; SALIR termina.")
    while True:
        pregunta = input("\nTú: ").strip()
        if pregunta.casefold() == "salir":
            break
        if pregunta.casefold() == "reiniciar":
            historial = nuevo_historial()
            print("Conversación reiniciada. Queda solo el mensaje system.")
            continue
        if not pregunta:
            continue
        try:
            resultado, actualizado, plan = procesar_turno(
                pregunta, historial, clave, modelo
            )
            historial = actualizado
            print("Plan:", json.dumps(plan, ensure_ascii=False))
            print("Chatbot:", resultado.get("mensaje") or
                  json.dumps(resultado["datos"], ensure_ascii=False, indent=2))
            if resultado["tipo"] == "confirmacion":
                if input("Confirmar (s/n): ").strip().casefold() == "s":
                    final = ejecutar(plan, confirmar=True)
                    historial[-1]["content"] = json.dumps(
                        {"plan": plan, "respuesta": final["datos"]}, ensure_ascii=False
                    )
                    print("FastAPI:", json.dumps(final["datos"], ensure_ascii=False, indent=2))
                else:
                    historial[-1]["content"] = json.dumps(
                        {"plan": plan, "respuesta": "La operación no fue confirmada."},
                        ensure_ascii=False,
                    )
            print(f"Mensajes en el historial: {len(historial)}")
        except HTTPError as error:
            print(f"Error HTTP {error.code}: {detalle_error(error)}".rstrip(": "))
            print("Revisa Groq o la FastAPI.")
        except (URLError, TimeoutError):
            print("No pude conectar con Groq o con la FastAPI.")
        except (ValueError, KeyError, IndexError, TypeError):
            print("No pude interpretar la respuesta. Revisa el JSON recibido.")


if __name__ == "__main__":
    main()
