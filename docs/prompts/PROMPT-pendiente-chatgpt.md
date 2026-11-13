# Prompt para ChatGPT: control de pendiente (pasos 5 y 6)

> **Ya no hace falta**: los pasos 5 y 6 se implementaron directamente (ver CHANGELOG). Se conserva como
> referencia de los requisitos.

**Cómo usarlo**
1. Adjunta a ChatGPT estos ficheros del proyecto (o un ZIP de `trainer-adapter/` y `frontend/src/`):
   - `trainer-adapter/coach/devices/zwift_hub.py`
   - `trainer-adapter/coach/devices/gear_shifter.py`
   - `trainer-adapter/coach/devices/wahoo.py`
   - `trainer-adapter/coach/devices/zwift_controllers.py`
   - `trainer-adapter/coach/app/server.py`, `runtime.py`, `settings.py`, `rider_profile.py`
   - `trainer-adapter/coach/session/session.py`, `trainer-adapter/coach/session/recording.py`
   - `trainer-adapter/tools/zwift_gear_test.py`
   - `trainer-adapter/tests/test_gear_shifter.py`, `tests/test_trainer_worker_shifting.py`, `tests/test_zwift_gear_test_run.py`
   - `frontend/src/types.ts`, `api.ts`, `components/Panels.tsx`, `pages/Dashboard.tsx`, `pages/Admin.tsx`
   - `backend/src/main/java/com/aicycling/coach/TrainerController.java`
   - `docs/pruebas/PRUEBA-control-paso3-marchas.md` (como modelo de guía)
2. Copia el texto de abajo (desde «Eres…») como mensaje.
3. Cuando te dé el código, ejecuta las pruebas antes de usar nada con el rodillo:
   `cd trainer-adapter && .venv/bin/python -m unittest discover -s tests -t .` y `cd frontend && npm run build`.

---

Eres un ingeniero senior que trabaja en un proyecto personal: **AI Cycling Coach**, una aplicación local para
entrenar con un rodillo inteligente. Te adjunto los ficheros relevantes. Necesito que implementes el **control de
pendiente** del rodillo, en dos pasos, con el mismo nivel de rigor y seguridad que el control de marchas que ya
existe. Lee primero el código adjunto y sigue sus patrones; no reinventes lo que ya está.

## Contexto técnico (hechos medidos, no suposiciones)

- Arquitectura: React (Vite, TypeScript) → API Java/Spring Boot (proxy que pasa el JSON tal cual) → adaptador Python
  3.13 con Bleak (un único bucle asyncio para todo el Bluetooth, `coach/bluetooth/ble_runtime.py`).
- Rodillo: **Wahoo KICKR CORE 2 con Zwift Cog**, firmware 3.5.11. Pesos del ciclista y la bici: los del perfil (en
  `rider_profile.py`). Mandos: dos Zwift Click v2.
- Control por el **protocolo Zwift nativo del rodillo** (servicio `0000fc82-…`, características `…0002` Async,
  `…0003` SyncRx para escribir sin respuesta, `…0004` SyncTx). Codificación en `coach/devices/zwift_hub.py`
  (portada de Serpentine, MIT).
  - Arranque: solo `RideOn 02 01`. El rodillo responde `RideOn 02 03`. **No enviar `41 08 05`**: este firmware
    responde "ZP: No handler for opcode 65".
  - HubCommand (tipo 0x04): campo 4 Simulation `{1 viento m/s×100 (sint, zigzag), 2 pendiente %×100 (sint, zigzag),
    3 CWa×10000 (usamos 5100), 4 Crr×100000 (usamos 400)}`; campo 5 Physical `{2 relación×10000, 4 kg bici×100,
    5 kg ciclista×100}`.
  - HubRequest 520 → el rodillo responde tipo 0x3C con la **relación de marcha aplicada** (así confirmamos cada
    marcha). **No sabemos aún si existe una confirmación de la pendiente**: hay que averiguarlo en el paso 5.
  - El rodillo ignora las marchas hasta recibir una pendiente no nula: hoy enviamos 0,4 % fijo al arrancar.
    No sabemos si enviar exactamente 0 % desactiva las marchas (Incyclist sustituye 0 por 0,01 %): compruébalo
    en el paso 5.
  - En modo Zwift, la velocidad que da FTMS es la virtual (cadencia × relación × ~2,1 m). RidingData (tipo 0x03)
    llega a 1 Hz con potencia y cadencia iguales a FTMS; su velocidad viene en m/s×100.
  - Medido: en llano (0,4 %) las marchas 1–3 quedan en el suelo de resistencia del rodillo (~28 W a 93 rpm).
- Seguridad que YA existe y que debes respetar y extender, no saltarte:
  - `gear_shifter.check_outgoing` / `SafeZwiftWriter`: solo se escribe en SyncRx; nunca ERG (power target),
    nunca en el servicio de actualización de firmware `FE59` (`8ec90003-…`); hoy rechaza cualquier pendiente
    distinta de 0,4 %. Tendrás que permitir pendientes **dentro de los topes configurados**, y nada más.
  - `GearShifter`: agrupa pulsaciones (80 ms), confirma cada marcha, reintenta, no endurece sin pedalear
    (< 40 rpm) o sin datos FTMS frescos (> 3 s), y al salir deja marcha 12 y 0,4 %.
  - `tools/zwift_gear_test.py`: prueba supervisada con plan fijo, `GuardedWriter` que solo permite los mensajes
    del plan, `ensure_live()` antes de cada envío, `--confirm` obligatorio, Ctrl+C y errores restauran el estado
    neutro. Sus tests simulan la prueba entera contra un rodillo falso.

## Lo que quiero

### Paso 5 — prueba supervisada de pendiente (herramienta, no la aplicación)
Crea `tools/zwift_grade_test.py` siguiendo exactamente el patrón de `tools/zwift_gear_test.py`:
- 10 s de referencia sin escribir nada; `RideOn 02 01`; 0,4 % + marcha 12 con los pesos; después una rampa suave
  con la marcha fija en 12: 0,4 → 1,0 → 2,0 → 1,0 → 0,4 %, 20 s por escalón; luego **una comprobación**: enviar
  0,0 % y después pedir la marcha 13 y la 12, para ver si el rodillo sigue confirmando marchas con 0 %; termina en
  marcha 12 y 0,4 %.
- `GuardedWriter` que solo deje pasar exactamente los mensajes del plan (y la restauración final).
- Nunca envíes nada sin datos FTMS en vivo; comprueba frescura antes de CADA envío, no solo en las esperas
  (este fallo ya nos pasó con las marchas).
- No endurezcas (subir pendiente) con cadencia < 40 rpm: salta ese escalón y anótalo.
- Registra TODO lo que llegue por Async y SyncTx, decodificado con `describe()`, para descubrir si hay alguna
  respuesta a los cambios de pendiente. Prueba también un HubRequest 512 tras cada cambio (Incyclist lo envía) y
  registra la respuesta, si la hay.
- Resumen por tramo: potencia, cadencia y velocidad FTMS medias, mensajes recibidos, y si las marchas siguen
  confirmándose con 0 %.
- Guarda el resultado en `diagnostics/zwift_grade_test_*.json` (`coach.app.paths.diagnostics_dir()`).
- Guía en español `docs/pruebas/PRUEBA-control-paso5-pendiente.md`, con la tabla segundo a segundo, la seguridad,
  los comandos en bloques (el usuario no puede copiar del chat) y qué debe enviar después. Modelo:
  `PRUEBA-control-paso3-marchas.md`.
- Tests: plan (orden, tiempos, ≥ 20 s por escalón, sin `41 08 05`), guardián (rechaza ERG, otras pendientes,
  FTMS control point, FE59), y **simulación completa** contra un rodillo falso con tiempos acortados
  (`patch.multiple`), incluyendo: ejecución normal termina en 12 / 0,4 %; telemetría que se corta → aborta y
  restaura; sin telemetría nunca escribe nada.

### Paso 6 — pendiente en la aplicación (después del paso 5; diseña ya el código, pero márcalo para ajustar con
los resultados del paso 5)
- Nuevo `coach/devices/grade_controller.py`, integrado en el mismo worker del rodillo que `GearShifter`
  (`wahoo.bluetooth_worker`) y solo cuando el control de marchas está activo (mismo canal nativo).
- La pendiente **solo cambia cuando el usuario la elige** (control manual en el Panel; más adelante rutas GPX).
  Nunca por sí sola.
- Cálculo: `objetivo` (lo que pide el usuario) → `efectiva` = objetivo × dificultad en subida, y × dificultad ×
  factor de bajada en descenso → recortada a [mínima, máxima] → `suavizada`: aproximación exponencial hacia la
  efectiva, τ = 4 s al endurecer y 1,5 s al suavizar (Serpentine) → `enviada`: solo si cambió ≥ 0,1 % y han pasado
  ≥ 1 s desde el último envío; reenviar cada 10 s aunque no cambie (Serpentine). Ajusta el tratamiento de 0 %
  según el paso 5.
- Valores por defecto (configurables en Ajustes, con validación estricta como `settings.py`: valores fuera de
  rango se rechazan, no se recortan): dificultad 50 % (como Zwift), factor de bajada 50 %, pendiente efectiva
  máxima +10 %, mínima −5 %.
- No endurecer con cadencia < 40 rpm o sin datos FTMS frescos (bajar sí). Al desconectar, mantener el estado y
  restaurarlo al reconectar; al salir, 0,4 % y marcha 12 (ya lo hace `GearShifter.finish`: coordínalo, no
  dupliques).
- Telemetría: `targetGradePercent` (pedida), `effectiveGradePercent` (tras dificultad y topes),
  `sentGradePercent` (última enviada), `gradeStatus`. Añade las nuevas columnas al CSV de sesión
  (`SESSION_FIELDS`) para que la sesión las guarde.
- API: `POST /grade {"gradePercent": n}` (409 si no hay control nativo activo; 400 si no es número o fuera de
  rango). Añade el reenvío en `TrainerController.java` como el de `/gear` (cuerpo JSON, conservar el código de
  estado del adaptador).
- Frontend: en el Panel, control de pendiente (−0,5 / +0,5 / 0 % y un deslizador que solo envía al soltar), y
  mostrar pedida, efectiva y enviada; en Ajustes, dificultad, factor de bajada y topes. Interfaz en español.
- Tests: `GradeController` con reloj falso (suavizado, umbral 0,1 %, 1 s, reenvío 10 s, topes, dificultad,
  bajadas, cadencia baja, reconexión), guardián ampliado, integración con el `FakeKickr` de
  `tests/test_trainer_worker_shifting.py` (marchas y pendiente a la vez), endpoint HTTP, y `npm run build` sin
  errores.

## Reglas de trabajo
- Solo `unittest` y la biblioteca estándar más `bleak`. Sin dependencias nuevas.
- Comentarios y nombres en el código en inglés; textos de la interfaz y guías en español.
- No toques funcionalidades que no tengan que ver con la pendiente. No borres código existente.
- Cada regla de seguridad debe tener su test. Si algo no puede comprobarse sin el rodillo real, dilo
  explícitamente y déjalo para la prueba supervisada; no lo des por bueno.
- Entrega: los ficheros completos nuevos o modificados (no fragmentos), la entrada para `CHANGELOG.md`, y una
  lista de lo que NO has podido verificar.
