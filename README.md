# OdontoAsistente

Chatbot de reservas para un consultorio odontológico **ficticio** (Armenia, Quindío). Una persona conversa en español; el sistema interpreta lo que pide, valida las reglas del negocio y guarda las reservas en SQLite.

- **Curso:** Electiva II (EAM-2026II) · Segundo corte
- **Integrante:** [tu nombre completo] (trabajo individual)
- **Repositorio:** https://github.com/darking2712/Odontoasistente

> Todos los datos (consultorio, dirección, clientes y reservas) son ficticios. No ingreses información personal real.

## Qué hace

- Informa servicios, precios, duración, horarios y ubicación.
- Consulta las horas libres para un servicio y una fecha.
- Crea, consulta, modifica y cancela reservas, siempre con una confirmación explícita antes de guardar.
- Rechaza las reservas que se cruzan con otra activa, que caen fuera del horario o en una fecha pasada.

**Límites:** no diagnostica, no recomienda tratamientos y no procesa pagos.

## Cómo está construido

```
Persona ──► Gradio (app_gradio.py)
                │
                ▼
        Python + Groq (chatbot_memoria.py, consulta_llm.py)
        interpreta el mensaje y devuelve un plan en JSON
                │  HTTP
                ▼
        FastAPI (main.py): reglas del negocio
                │
                ▼
        SQLite (almacen_sqlite.py → reservas.db)
```

| Herramienta | Para qué se usa |
|---|---|
| Gradio | Pantalla del chat y botones Confirmar / Descartar / Reiniciar |
| Groq (modelo de lenguaje) | Interpretar el mensaje: acción, servicio, fecha, hora, cliente y código |
| FastAPI | Ejecutar las operaciones del negocio y validar los datos |
| SQLite | Guardar las reservas de forma persistente |

El modelo **solo interpreta**; no puede guardar nada. Crear, modificar o cancelar exige pulsar **Confirmar operación** en la interfaz.

### Archivos

| Archivo | Contenido |
|---|---|
| `app_gradio.py` | Interfaz Gradio (puerto 7860) |
| `chatbot_memoria.py` | Historial de la conversación y llamada a Groq por turno |
| `consulta_llm.py` | Prompt, llamada a Groq y llamadas a la API (`interpretar`, `ejecutar`) |
| `main.py` | API FastAPI (puerto 8011): servicios, disponibilidad y reservas |
| `almacen_sqlite.py` | Tabla `reservas`, transacciones y control de cruces |
| `negocio.json` | Catálogo, precios, duraciones y horarios |
| `reservas.db` | Base SQLite con reservas ficticias de prueba |
| `probar_demo.py` | Prueba automática (no toca `reservas.db`) |
| `docs/` | Bitácora, presentación y evidencias |

Material de la versión anterior (Flowise + JSON), conservado solo para la comparación: `Demo*.json`, `puente_flowise.js`, `prompt_sistema.txt`, `reservas.json` y `main_sqlite_ejemplo.py`. **No forman parte de la versión del segundo corte.**

## Requisitos e instalación

- Python 3.10 o superior (desarrollado con Python 3.14).
- Una API key de [Groq](https://console.groq.com/).

Desde la carpeta del repositorio (comandos para Windows PowerShell):

```powershell
git clone https://github.com/darking2712/Odontoasistente.git
cd Odontoasistente
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

En Linux o macOS usa `.venv/bin/python` en lugar de `.\.venv\Scripts\python.exe`.

## Configuración

| Variable | Obligatoria | Descripción |
|---|---|---|
| `GROQ_API_KEY` | Sí | Clave de Groq. **No la escribas en ningún archivo del repositorio.** |
| `GROQ_MODEL` | Sí | ID del modelo de Groq, por ejemplo `openai/gpt-oss-20b`. Verifica que Groq lo siga ofreciendo. |
| `CHATBOT_API_URL` | No | Dirección de FastAPI. Por defecto `http://127.0.0.1:8011`. |

Se definen en la terminal donde se inicia Gradio y solo duran esa sesión:

```powershell
$env:GROQ_API_KEY = "pega-aqui-tu-clave"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
$env:CHATBOT_API_URL = "http://127.0.0.1:8011"
```

## Datos y ejecución

`reservas.db` se crea sola si no existe (tabla `reservas`). El repositorio incluye una con reservas ficticias de prueba.

Para importar el histórico de la versión JSON (opcional):

```powershell
.\.venv\Scripts\python.exe almacen_sqlite.py --migrar reservas.json
```

Se usan **dos terminales**, ambas desde la carpeta del proyecto.

**Terminal 1: API.** Debe ejecutarse con un solo proceso.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8011
```

**Terminal 2: interfaz.**

```powershell
$env:GROQ_API_KEY = "pega-aqui-tu-clave"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
$env:CHATBOT_API_URL = "http://127.0.0.1:8011"
.\.venv\Scripts\python.exe app_gradio.py
```

Direcciones:

- Interfaz del chat: http://127.0.0.1:7860
- Documentación interactiva de la API: http://127.0.0.1:8011/docs

## Comprobación

**1. Prueba automática** (no necesita Groq ni internet; usa una base temporal):

```powershell
.\.venv\Scripts\python.exe probar_demo.py
```

Resultado esperado: una línea `[OK]` por cada comprobación y, al final,

```
OK: validaciones, concurrencia, persistencia, cruces, modificación, cancelación, chat y errores.
```

**2. Prueba manual** con las dos terminales encendidas. En http://127.0.0.1:7860 escribe, con una fecha futura que sea día hábil:

> Quiero una valoración el AAAA-MM-DD a las 09:00 a nombre de Laura

El chat debe mostrar un resumen con el precio. Pulsa **Confirmar operación**: responde con un código de 8 caracteres. Compruébalo en http://127.0.0.1:8011/docs (`GET /reservas/{codigo}`).

### Errores frecuentes

| Mensaje | Causa y solución |
|---|---|
| `Configura GROQ_API_KEY y GROQ_MODEL e inicia de nuevo.` | Faltan las variables en la terminal 2. Defínelas y reinicia `app_gradio.py`. |
| `No pude conectar con Groq o FastAPI.` | La API no está encendida (terminal 1), el puerto o `CHATBOT_API_URL` no coinciden, o no hay internet. |
| `Error HTTP 401` o `403` | Clave de Groq incorrecta o bloqueada. |
| `Error HTTP 404` al interpretar | El modelo de `GROQ_MODEL` ya no existe en Groq. Cambia el ID. |
| `Error HTTP 409` al confirmar | Esa hora se ocupó después del resumen. Pide otra hora. |
| `Error HTTP 422` | Datos inválidos: fecha pasada, día cerrado, hora fuera del horario o del paso de 30 min. |
| `Error HTTP 503` | La API no pudo acceder a SQLite. Revisa que `reservas.db` no esté bloqueada por otro programa y reintenta. |
| `Address already in use` | El puerto 8011 o 7860 está ocupado. Cierra el otro proceso o cambia el puerto. |

## Reglas del negocio

- Lunes a viernes 08:00–18:00; sábado 08:00–13:00; domingo cerrado.
- Una persona atendida a la vez (capacidad 1). Las horas se ofrecen en pasos de 30 minutos.
- La atención debe terminar dentro del horario. Duraciones: valoración 30 min, limpieza 45, blanqueamiento 60, ortodoncia 30, extracción 45.
- Dos reservas activas no pueden cruzarse. Un intervalo que empieza justo cuando termina otro sí es válido.
- Cancelar libera el horario y conserva la fila con estado `cancelada`.
- La comprobación del horario y el guardado ocurren en la misma transacción de SQLite.

### Endpoints de la API

| Método y ruta | Operación |
|---|---|
| `GET /servicios` | Catálogo, precios y horarios |
| `GET /disponibilidad?fecha=AAAA-MM-DD&servicio=clave` | Horas libres |
| `GET /reservas` | Lista las reservas |
| `POST /reservas` | Crea (requiere `confirmado: true`) |
| `GET /reservas/{codigo}` | Consulta |
| `PUT /reservas/{codigo}` | Modifica servicio, fecha y hora (requiere `confirmado: true`) |
| `DELETE /reservas/{codigo}?confirmado=true` | Cancela |
| `POST /chat` | Puente de la versión Flowise; Gradio no lo usa |

## Limitaciones conocidas

- La API no tiene autenticación: es solo para uso local. No la publiques en internet.
- El historial y la solicitud pendiente de Gradio viven en memoria de esa pestaña: al recargar la página se pierden. Las reservas guardadas no.
- El modelo puede interpretar mal un mensaje ambiguo. Por eso la fecha se pide en formato AAAA-MM-DD y nada se guarda sin confirmar.
- La tabla guarda la duración de cada reserva, no el precio: el precio se toma del catálogo actual (`negocio.json`).
- Solo se atiende a una persona a la vez; el código no soporta varios profesionales.

## Documentación del segundo corte

- [Bitácora del segundo corte](docs/Bitacora_Segundo_Corte.md)
- [Presentación en PDF](docs/Presentacion_Segundo_Corte.pdf)
- [Evidencias](docs/evidencias/)
