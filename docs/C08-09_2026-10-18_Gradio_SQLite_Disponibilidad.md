---
tipo: bitacora-clase
curso: Creación de Chatbots con IA
periodo: EAM-2026II
equipo: Individual
corte: 2
semana: 8-9
clase: 08-09
fecha: 2026-10-18
estado: en-progreso
tags:
  - chatbots
  - bitacora
  - gradio
  - sqlite
  - disponibilidad
---

# Bitácora — Clase 08–09

> [!tip] Cómo usar esta plantilla
> Duplica esta nota al finalizar cada clase y nómbrala `C##_AAAA-MM-DD_Tema`. Completa los campos entre corchetes y conserva enlaces verificables.

## 1. Datos de la sesión

| Campo    | Registro                                                                                                                                                                                                       |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tema     | Laboratorio 08–09: interfaz con Gradio, reservas en SQLite y disponibilidad con duración del servicio                                                                                                          |
| Objetivo | Que el chatbot funcione desde Gradio con una conversación por sesión y que la FastAPI guarde las reservas en SQLite, comprobando la duración del servicio y los intervalos ocupados antes de crear una reserva |
| Proyecto | OdontoAsistente                                                                                                                                                                                                |
| Inicio   | 9:00 a.m.                                                                                                                                                                                                      |
| Cierre   | 12:00 m.                                                                                                                                                                                                       |

## 2. Participación y responsabilidades

| Integrante | Asistió | Rol de la clase | Responsabilidad asumida | Aporte verificable |
|---|:---:|---|---|---|
| Kevin Londoño Hernandez | Sí | Desarrollo individual | Adaptar `main.py` para usar `AgendaSQLite`, encender Gradio, ejecutar las pruebas de disponibilidad y documentar las evidencias | `main.py` adaptado, `reservas.db` y las capturas de la sección 6 |

## 3. Reto aplicado al proyecto

### Funcionalidad trabajada

Se reemplazó el almacenamiento en `reservas.json` por SQLite. `main.py` ahora crea un objeto de agenda (`AgendaConsultorio`, una subclase de `AgendaSQLite`) y todos los endpoints de reservas (`/disponibilidad`, `/reservas`, `/reservas/{codigo}`) leen y escriben en `reservas.db`. Se conservaron las rutas sin prefijo `/api`, la validación `confirmado` y las reglas de OdontoAsistente (horario por día, con el sábado hasta las 13:00, y no reservar horas que ya pasaron hoy).

La disponibilidad ya no compara solo la hora de inicio: cada reserva guarda su duración y la API rechaza cualquier intervalo que se cruce con una reserva activa. La comprobación y el `INSERT` se hacen dentro de una misma transacción.

Después se encendió `app_gradio.py` con las variables `CHATBOT_API_URL`, `GROQ_MODEL` y `GROQ_API_KEY`, y se probó el flujo completo desde la pantalla: consulta de disponibilidad, reserva en varios turnos, confirmación y comprobación de la fila en SQLite.

### Criterios de aceptación

- [x] Los endpoints de reservas consultan y escriben en `reservas.db`, y no en el JSON.
- [x] La disponibilidad descuenta el intervalo completo de una reserva según su duración.
- [x] Un servicio de 30 minutos a las 10:30 se rechaza (HTTP 409) cuando ya hay un servicio de 60 minutos a las 10:00.
- [x] Una reserva que empieza justo cuando termina la anterior se acepta.
- [x] Una reserva rechazada no deja ninguna fila en la base.
- [x] Cancelar una reserva libera su intervalo en la disponibilidad.
- [x] Descartar una solicitud sin ejecutar no crea ninguna fila.
- [x] Reiniciar el chat vacía la conversación y las filas aceptadas siguen guardadas.
- [x] Dos conversaciones (ventana normal y privada) conservan datos propios y solo una reserva del mismo intervalo es aceptada.
- [x] Las reservas continúan en la base después de reiniciar la API.
- [x] La API key no está en el código ni en las evidencias entregadas (revisar antes de entregar).

### Resultado de las pruebas de la guía (sección 11)

| Prueba                                                                           | Resultado                             | Evidencia                                     |
| -------------------------------------------------------------------------------- | ------------------------------------- | --------------------------------------------- |
| 1. Consultar servicios y disponibilidad desde Gradio                             | Cumplida                              | Sección 6, evidencias 5 y 7                   |
| 2–3. Completar una solicitud en varios turnos, confirmar y ver la fila en SQLite | Cumplida: reserva `F45FD1A4` de Laura | Sección 6, respuesta de FastAPI y evidencia 6 |
| 4. Servicio de 60 min a las 10:00 y otro de 30 min a las 10:30                   | Cumplida: rechazo con HTTP 409        | Sección 6, evidencias 8, 9 y 10               |
| 5. Reserva que empieza justo al terminar la anterior                             | Cumplida: aceptada con HTTP 201       | Sección 6, evidencias 11 y 12                 |


### Archivos o componentes modificados

- `main.py` (modificado): se quitaron `leer()`, `guardar()` y el modelo `Registro`; se creó `AgendaConsultorio(AgendaSQLite)`; los endpoints llaman a `agenda.disponibilidad()`, `agenda.crear()`, `agenda.consultar()` y `agenda.cancelar()`; la función `ejecutar()` traduce los errores del almacén a HTTP 404, 409 y 422; se actualizaron los textos del chat que todavía hablaban de la barbería (servicios y ejemplo de código).
- `almacen_sqlite.py`, `app_gradio.py` y `main_sqlite_ejemplo.py` (entregados por el docente, sin cambios): el último se usó solo como referencia.
- `reservas.db` (nuevo): se crea al iniciar la API. En las pruebas contiene las reservas de Laura y Pedro.
- `reservas.json`: ya no lo usa la API. El primer `SELECT` mostró solo la reserva de prueba de Laura, por lo que la migración de reservas anteriores no se ejecutó. [Completar si se migró]

## 4. Decisiones técnicas

| Decisión | Razón | Alternativa descartada |
|---|---|---|
| Crear la subclase `AgendaConsultorio` en `main.py` | `AgendaSQLite` acepta un solo horario para todos los días, pero el consultorio cierra a las 13:00 los sábados. La subclase valida el horario de cada día y rechaza horas que ya pasaron hoy | Usar un horario único de 08:00 a 18:00, que habría permitido reservar el sábado por la tarde |
| Llamar `ejecutar()` a la función que traduce errores a HTTP | La guía la llama `responder()`, pero ese nombre ya lo usa el endpoint `/chat` para armar su respuesta y se habrían pisado | Renombrar la función del chat, que tiene más usos |
| Mantener la clave `horarios` en la respuesta de `/disponibilidad` | El almacén devuelve `horas`, pero el cliente `consulta_llm.py` ya lee `horarios`. Así no hubo que cambiar el cliente | Cambiar el cliente para que lea `horas` |
| Tomar el precio del catálogo `negocio.json` y no guardarlo en la tabla | La tabla de la guía solo guarda duración. El precio se agrega al responder | Añadir una columna `precio_cop` a la tabla |
| Conservar las rutas sin `/api` | `consulta_llm.py` ya usa `/servicios`, `/disponibilidad` y `/reservas` | Usar las rutas `/api/...` de la referencia y adaptar el cliente |

## 5. Problemas y soluciones

| Problema encontrado | Causa identificada | Solución aplicada | ¿Cómo se verificó? |
|---|---|---|---|
| Al enviar el primer mensaje en Gradio apareció "Error HTTP 401. Revisa Groq o FastAPI." | Causa probable: la API key de Groq no se había cargado bien en esa terminal. FastAPI no pide autenticación, así que el 401 solo podía venir de Groq | Se detuvo Gradio, se volvió a pedir la clave con `Read-Host -AsSecureString`, se asignó a `$env:GROQ_API_KEY` y se reinició `app_gradio.py` en la misma terminal | Después de recargarla, el chat respondió y se completó la reserva de Laura |
| Gradio mostró "Confirma o descarta la solicitud pendiente primero." | No era un fallo: `app_gradio.py` bloquea nuevos mensajes mientras haya una operación pendiente de confirmar | Se confirmó o se descartó la solicitud pendiente antes de seguir escribiendo | El siguiente mensaje se envió sin ese aviso |
| Gradio mostró "FastAPI respondió con HTTP 409" al confirmar la valoración de las 10:30 | Es el comportamiento esperado: el intervalo se cruza con el blanqueamiento de 10:00 a 11:00. Gradio solo muestra el código, no el motivo | Se repitió la misma petición en `/docs` para ver el mensaje exacto | `/docs` devolvió 409 con "El intervalo solicitado se cruza con una reserva activa" y el `SELECT` no mostró ninguna fila de Pedro |

## 6. Evidencias

| Tipo    | Descripción                                                                                                                              | Enlace o ruta                             |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Captura | 1. Instalación de Gradio 6.30.0 con `pip` en el entorno virtual del proyecto                                                             | ![[C08-09_01_gradio_instalado.png]]       |
| Captura | 2. `app_gradio.py` en ejecución en `http://127.0.0.1:7860`                                                                               | ![[C08-09_02_gradio_en_ejecucion.png]]    |
| Captura | 3. Error HTTP 401 de Groq en el primer intento, antes de cargar bien la clave                                                            | ![[C08-09_03_error_401_groq.png]]         |
| Captura | 4. Clave pedida con `Read-Host -AsSecureString` (oculta) y Gradio reiniciado en la misma terminal                                        | ![[C08-09_04_clave_recargada.png]]        |
| Demo    | 5. Consulta de servicios en Gradio: el chat devolvió el catálogo de `negocio.json`                                                       | `negocio.json`                            |
| Demo    | Reserva confirmada desde Gradio. Respuesta de FastAPI: `F45FD1A4`, Laura, `blanqueamiento`, 2026-10-20 a las 10:00, 60 minutos, `activa` | ver bloque de código abajo                |
| Captura | 6. `SELECT` en `reservas.db` con la fila de Laura guardada                                                                               | ![[C08-09_06_sqlite_reserva_laura.png]]   |
| Captura | 7. Disponibilidad de una valoración el 2026-10-20 después de reservar: saltan de 09:30 a 11:00                                           | ![[C08-09_07_disponibilidad_despues.png]] |
| Captura | 8. Gradio muestra HTTP 409 al confirmar la valoración de las 10:30                                                                       | ![[C08-09_08_gradio_409_cruce.png]]       |
| Captura | 9. `SELECT` después del rechazo: solo sigue la fila de Laura                                                                             | ![[C08-09_09_sqlite_sin_fila_pedro.png]]  |
| Captura | 10. `/docs`, `POST /reservas` para Pedro a las 10:30: 409 con el mensaje del cruce                                                       | ![[C08-09_10_docs_409_cruce.png]]         |
| Captura | 11. `/docs`, `POST /reservas` para Pedro a las 11:00: 201, aceptada                                                                      | ![[C08-09_11_docs_201_pegada.png]]        |
| Captura | 12. `SELECT` con las dos filas activas: Laura a las 10:00 y Pedro a las 11:00                                                            | ![[C08-09_12_sqlite_dos_filas.png]]       |
| Código  | `AgendaConsultorio`, `ejecutar()` y los endpoints en `main.py`                                                                           | `main.py`                                 |

Respuesta de FastAPI al confirmar la reserva de Laura desde Gradio:

```json
{
  "codigo": "F45FD1A4",
  "cliente": "Laura",
  "servicio": "blanqueamiento",
  "fecha": "2026-10-20",
  "hora": "10:00",
  "duracion_minutos": 60,
  "estado": "activa",
  "precio_cop": 350000
}
```

## 7. Uso de inteligencia artificial

> [!important] Registrar la IA no reemplaza la explicación técnica. El equipo debe verificar, adaptar y comprender cualquier resultado utilizado.

| Herramienta        | Objetivo o pregunta                                                                                                                                                | Qué se utilizó                                                                                                     | Cómo se verificó                                                                                                                                                                                                                              | Qué se modificó |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| Claude (Anthropic) | Entender el laboratorio, adaptar `main.py` a `AgendaSQLite` conservando las rutas y reglas de OdontoAsistente, y resolver el error HTTP 401 y los avisos de Gradio | `main.py` adaptado con la subclase `AgendaConsultorio` y la función `ejecutar()`, y los pasos para encender Gradio | Se probó la lógica de la agenda con datos de prueba antes de usarla. Después se ejecutó contra Groq, FastAPI y SQLite reales: disponibilidad, rechazo del cruce con 409, reserva pegada aceptada con 201 y consultas `SELECT` a `reservas.db` |                 |

## 8. Defensa técnica y retroalimentación

| Campo | Registro |
|---|---|
| Integrante que defendió | Kevin Londoño Hernandez |
| Pregunta recibida | [Pregunta] |
| Respuesta resumida | [Respuesta] |
| Retroalimentación docente | [Observación] |
| Mejora acordada | [Acción concreta] |

## 9. Aprendizajes

- **Concepto comprendido:** el recorrido completo de una reserva. El mensaje llega a `enviar()` en `app_gradio.py`, que llama a `procesar_turno()` de `chatbot_memoria.py`. El historial (`messages[]`) vive en el estado de la sesión de Gradio (`estado["historial"]`), en memoria y por conversación, y no en la base. Cuando la persona pulsa **Confirmar operación**, `confirmar()` llama a `ejecutar()` de `consulta_llm.py`, que hace la petición HTTP a `POST /reservas`. Ese endpoint, `crear()` en `main.py`, llama a `agenda.crear()`, que ejecuta `INSERT INTO reservas VALUES (?, ?, ?, ?, ?, ?, ?)`. La comprobación previa corresponde a `SELECT hora, duracion_minutos FROM reservas WHERE fecha=? AND estado='activa' AND codigo<>?`, y cancelar corresponde a `UPDATE reservas SET estado='cancelada' WHERE codigo=?`.
- **Por qué una misma transacción:** `conexion(escritura=True)` abre la transacción con `BEGIN IMMEDIATE`, que reserva la escritura antes de comprobar. Así, si dos personas piden el mismo intervalo a la vez, la segunda espera hasta que la primera termine y entonces ve el intervalo ocupado y recibe 409. Si la comprobación y el guardado fueran pasos separados, las dos podrían ver el intervalo libre y las dos guardarían. Si algo falla dentro de la transacción, se hace `rollback()` y no queda ninguna fila a medias.
- **Algo que aún genera duda:** [Duda pendiente]
- **Qué haríamos diferente:** comprobar la API key con un mensaje sencillo apenas se enciende Gradio, antes de empezar las pruebas largas, para no perder tiempo con el error 401 en medio de la prueba.

## 10. Revisión antes de entregar

- [x] Todos los integrantes registraron un aporte verificable.
- [x] Los enlaces y rutas de evidencia funcionan.
- [x] Los criterios de aceptación están actualizados.
- [x] El uso de IA fue declarado y verificado.
- [x] El equipo puede explicar las decisiones registradas.
- [x] El paquete y las capturas no contienen la API key.
