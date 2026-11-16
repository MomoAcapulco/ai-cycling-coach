# Changelog

Historial de versiones (lo que antes estaba en un README por versión). La más reciente, arriba.


## AI Cycling Coach v4.3.0 — Base sólida, autodescubrimiento y página de Ajustes

### Control del rodillo: preparación
- Paso 1 hecho (`tools/trainer_probe.py`, solo lectura): el KICKR CORE 2 (firmware 3.5.11) tiene el protocolo Zwift (`FC82`), visible al conectar aunque no se anuncia.
- `coach/devices/zwift_hub.py`: codificación del protocolo Zwift del rodillo (portada de Serpentine, MIT) y tabla de 24 marchas de Zwift (neutra 12 = 2,40).
- Paso 2 preparado (`tools/zwift_hub_probe.py --confirm`): abre el canal Zwift y escucha, con un bloqueo que solo permite los dos mensajes de arranque. Guía: `docs/pruebas/PRUEBA-control-paso2-canal-zwift.md`.
- Paso 2 hecho (`diagnostics/zwift_hub_probe_20261112_154311.json`): el rodillo contesta `RideOn 02 03` y manda RidingData a 1 Hz con la misma potencia y cadencia que FTMS. Corregido: la velocidad del canal Zwift viene en m/s×100, no en km/h×100. El mensaje `41 08 05` no lo soporta este firmware ("No handler for opcode 65") y sobra. El campo 6 (23003) no cambió durante el minuto: candidato a relación de marcha actual, a confirmar en el paso 3.
- Paso 3 preparado (`tools/zwift_gear_test.py --confirm`): 10 s de referencia en modo libre, marcha 12 con tus pesos y 0,4 %, y luego 13 → 12 → 11 → 12 cada 15 s; termina en 12. Bloqueo de escrituras según el plan; nunca envía sin datos del rodillo y comprueba que siguen llegando antes de cada envío; con cadencia < 40 rpm no endurece; con Ctrl+C o sin datos vuelve a la marcha 12. Simulación completa contra un rodillo falso en los tests. Guía: `docs/pruebas/PRUEBA-control-paso3-marchas.md`.
- Paso 3 hecho (`diagnostics/zwift_gear_test_20261112_155523.json`): las 5 marchas fueron confirmadas por el rodillo en 0,04–0,23 s; la respuesta 0x3C a HubRequest 520 trae la relación aplicada. A 60 rpm: modo libre 118 W; marcha 12 ≈ 75 W; marcha 13 ≈ 97 W; marcha 11 ≈ 69 W. En modo Zwift, la velocidad FTMS es la virtual (cadencia × relación × ~2,1 m).
- **Paso 4: marchas que mueven el rodillo desde la aplicación** (`coach/devices/gear_shifter.py`).
  - Mandos y botones del panel; 24 marchas de Zwift; empieza en la 12.
  - Pulsaciones agrupadas (80 ms); cada marcha confirmada por el rodillo, con 3 reintentos.
  - Sin pedalear o sin datos no endurece; al salir vuelve a la 12; al reconectar restablece la marcha.
  - Solo escribe en el canal Zwift: sin ERG, sin pendiente y nunca en el servicio de firmware.
  - Se activa en Ajustes («Control de marchas del rodillo») o con `GEAR_CONTROL_ENABLED`; desactivado por defecto.
  - El panel muestra la marcha confirmada por el rodillo.
  - Endpoint `POST /gear`.
  - Guía: `docs/pruebas/PRUEBA-control-paso4-marchas-en-la-app.md`.
- **Sesiones de entrenamiento**:
  - Se manejan con «Iniciar / Pausar / Continuar / Terminar» en el Panel, en modo rodillo real o simulador; ya no hay grabación de 10 minutos fijos.
  - Cada sesión guarda un CSV a 1 Hz (con la marcha confirmada; se puede reproducir) y un resumen JSON (`coach/session/metrics.py`): tiempo, tiempo en movimiento, distancia, kJ, potencia media y máxima, NP, cadencia, pulso, IF/TSS si hay FTP y tiempo por marcha.
  - Página **Sesiones**: resumen, descarga (CSV, resumen y captura) y «Ver en replay».
  - Se termina sola al cambiar ajustes, al cerrar la aplicación o al llegar a 4 h.
  - La captura Bluetooth en bruto es opcional y va con cada sesión.
- **Carpeta de datos junto a las versiones**: `~/dev/ai-cycling-coach-data/` (`AI_COACH_HOME`), visible para el análisis. Al arrancar se copia lo que hubiera en `~/.ai-cycling-coach/`, sin sobrescribir ni borrar.
- Sesión del 12-11 (`diagnostics/ride_20261112_161053_507197.csv`): 36 marchas confirmadas (de la 1 a la 21). En las marchas 1–3 la potencia se queda en ~28 W a ~93 rpm (suelo de resistencia del rodillo en llano), lo que explica que apenas se noten.
- Las herramientas de diagnóstico guardan en `diagnostics/` dentro del proyecto, para compartir los resultados.
- **Paso 5 preparado: rampa suave de pendiente** (`tools/zwift_grade_test.py --confirm`).
  - Plan: 10 s de referencia; 0,4 % y marcha 12; después 1 → 1,5 %, reenvío de la marcha 12 (¿se mantiene la pendiente?), 1 → 0,4 → 0 %, marchas 13 y 12 con 0 % (¿siguen funcionando las marchas?) y vuelta a 0,4 %. Nunca pasa del 1,5 % y ningún escalón supera el 0,6 % (unos 35–40 W a 65 rpm).
  - Tras cada cambio de pendiente envía HubRequest 512 y registra todo lo que contesta el rodillo, para saber si confirma la pendiente.
  - Mismas protecciones que el paso 3: bloqueo de escrituras según el plan, comprobación de datos antes de cada envío, nada sin datos, cadencia < 40 rpm → salta los escalones que endurecen, y Ctrl+C o errores → 0,4 % y marcha 12.
  - Simulación completa en los tests. Guía: `docs/pruebas/PRUEBA-control-paso5-pendiente.md`.
- **Paso 6 hecho en código, pendiente de probar con el rodillo: pendiente en la aplicación** (`coach/devices/grade_controller.py`).
  - La pendiente **solo cambia cuando la eliges** en el Panel (−0,5 / +0,5 / llano 0 % y un deslizador que envía al soltar). Hasta entonces el rodillo sigue en el 0,4 % de arranque.
  - Pedida → efectiva (× dificultad, y en bajada × factor de bajadas, dentro de tus límites) → suavizada (τ 4 s al endurecer, 1,5 s al suavizar, y nunca más de 1 % por segundo) → enviada (cambio ≥ 0,1 %, como mucho una vez por segundo, y reenvío cada 10 s).
  - Sin pedalear (< 40 rpm) o sin datos no endurece; suavizar siempre se puede. Al reconectar vuelve a subir poco a poco desde 0,4 %, nunca de golpe. Al salir, 0,4 % y marcha 12.
  - El 0 % exacto se envía como 0,01 % (como Incyclist) hasta que el paso 5 diga si es seguro.
  - Perfil del ciclista (Ajustes): dificultad (50 %), factor de bajadas (50 %), pendiente efectiva máxima (+10 %) y mínima (−5 %); fuera de rango se rechaza; se aplica al momento.
  - Guardián de escrituras ampliado: pendientes solo dentro de tus límites y nunca fuera de −10 % … +20 %; viento, CdA y Crr fijos.
  - Se activa junto con el control de marchas (mismo canal). Endpoint `POST /grade` (409 sin control nativo, 400 si el valor no vale) y su reenvío en la API Java.
  - Telemetría y CSV de sesión: `targetGradePercent`, `effectiveGradePercent`, `sentGradePercent`, `gradeStatus`.
  - El panel muestra «enviada», no «aplicada»: el rodillo aún no confirma la pendiente.
- `describe()` muestra también los campos crudos de cualquier respuesta 0x3C.
- **Carretera virtual** (`coach/session/virtual_ride.py`): velocidad, distancia, altitud y desnivel calculados con física.
  - Por qué: en modo Zwift la velocidad del rodillo es cadencia × relación × ~2,1 m y **no baja al subir**: a 70 rpm en la marcha 12 marca ~21 km/h al 0 % y al 8 %. Con ella, la distancia y el desnivel salían inflados en cada subida. Zwift también calcula la velocidad a partir de la potencia.
  - Modelo: fuerzas de pedaleo, gravedad, rodadura (Crr 0,004) y aire (CdA 0,40 m²), con la inercia del ciclista. Por ejemplo, con 200 W y 89 kg en total: ~32 km/h en llano, ~14 km/h al 5 % y ~10 km/h al 8 %. Sin pedalear se rueda por inercia (y se acelera en las bajadas); nunca hacia atrás.
  - **La pendiente cambia por distancia, no por tiempo**: como mucho 1 % cada 20 m (configurable de 5 a 100 m en el perfil). Pasar del 0 al 5 % lleva ~100 m. Parado no cambia.
  - El desnivel usa la pendiente de la carretera, no la del rodillo tras la dificultad (como Zwift: con dificultad al 50 % sientes la mitad, pero has subido toda la montaña).
  - El control de pendiente del rodillo sigue a la carretera: ya no suaviza por tiempo (τ 4 s / 1,5 s); queda solo una red de seguridad de +1 %/s como máximo al endurecer. Corregido: los cambios de menos de 0,1 % ya no se mandan cada segundo mientras la carretera todavía está cambiando.
  - Funciona en el simulador (`POST /grade` también en modo SIMULATOR, solo mueve la carretera), para probarla sin rodillo. Guía: `docs/pruebas/PRUEBA-pendiente-en-el-simulador.md`.
- **Métricas nuevas**:
  - En directo: velocidad en la carretera virtual (y la del rodillo, aparte), pendiente de la carretera, desnivel, altitud, VAM (m/h) y W/kg.
  - En la sesión: la distancia sale de la carretera virtual; desnivel acumulado, VAM de las subidas (con al menos 1 minuto subiendo), velocidad media, W/kg medio, mejores esfuerzos de 5 s, 1, 5 y 20 min (sin cruzar cortes de datos) y **FTP estimado** (95 % de los mejores 20 min).
  - CSV de sesión: `roadGradePercent`, `rideSpeedKph`, `rideDistanceKm`, `altitudeM`, `elevationGainM`, `vamMh`, `wattsPerKg`.
- **Autodescubrimiento con varios dispositivos** (ADR-002, revisión del 13-11):
  - Se recuerdan **todos** los dispositivos usados de cada tipo, no solo el último, con la fecha de último uso y uno preferido. El `devices.json` antiguo se lee y se convierte sin perder nada.
  - Un único escaneo reúne los candidatos: se usa el preferido si está cerca; si no, el último usado. Si no hay ninguno conocido y solo uno nuevo, se usa y se recuerda.
  - **Ya no se adivina**: con varios desconocidos y ninguno conocido (por ejemplo, la banda de otra persona al lado), aparecen en Ajustes para elegir y el Panel lo avisa. Antes se cogía el primero que respondía. En los mandos solo se pregunta si hay dos que anuncian el mismo lado.
  - Ajustes → Dispositivos: por cada tipo, la lista con «Usar este» y «Olvidar». El pulsómetro y los mandos cambian al momento; el rodillo, en la siguiente conexión. Si hay un ID fijado en `.env`, se muestra.
  - **Sin filtros de nombre**: los dispositivos se encuentran solo por su tipo, de cualquier marca. `WAHOO_DEVICE_NAME` y `HR_DEVICE_NAME` se ignoran, con un aviso al arrancar (antes, `HR_DEVICE_NAME=HR50` impedía usar una banda de otra marca).
  - API: `GET /devices` (con `known`, `pending` y `envFilters`), `POST /devices/<tipo>/use`, `DELETE /devices/<tipo>?address=…`.
- **Paso 5 hecho** (`diagnostics/zwift_grade_test_20261113_123554.json`). Los cambios se notaron naturales, sin exagerar.
  - **El rodillo confirma la pendiente**: la respuesta a la petición 512 trae, en su campo 6, la pendiente aplicada. Coincidió 7 de 7 veces y llega en ~0,3 s.
  - **El 0 % exacto funciona**: el rodillo lo aplica, y las marchas siguen confirmándose y notándose con 0 %.
  - **Mandar una marcha no borra la pendiente.**
  - **La velocidad del rodillo** en modo Zwift es una velocidad física con inercia, pero para la pendiente que aplica el rodillo (tras la dificultad). A igual potencia y pendiente, nuestra carretera virtual da ±1 km/h de lo que da él, y CdA 0,40 es el que mejor encaja. Corregida la explicación anterior, que la describía como una simple cuenta de cadencia por marcha.
- **Pendiente confirmada** (`grade_controller.py`): tras cada envío se pide la 512. El Panel muestra «Aplicada ✓» solo si el rodillo lo confirma; si no contesta, se reintenta 3 veces y luego aparece «sin confirmar», y el reenvío cada 10 s sigue intentándolo. El 0 % se manda como 0 (antes, 0,01 %).
- **Correcciones tras la prueba en la aplicación del 13-11**:
  - El reloj grande del Panel mostraba el tiempo desde que arrancó el adaptador. Ahora es el **tiempo de la sesión**: empieza al pulsar «Iniciar sesión», sigue corriendo aunque dejes de pedalear y descuenta las pausas. Sin sesión muestra «--:--».
  - Al iniciar una sesión nueva, las gráficas, el perfil del recorrido y la pendiente máxima **empiezan de cero**, con el tiempo de la sesión. Antes arrastraban todo lo anterior. Al terminar, la última sesión se queda en pantalla hasta empezar otra.
  - Botones ±0,5 % de la pendiente: varias pulsaciones seguidas solo contaban una por segundo, porque cada pulsación sumaba a la última lectura de telemetría y el botón se bloqueaba mientras se enviaba. Ahora cada pulsación suma al instante y se envía una sola vez, 0,3 s después de la última, con el total. El deslizador no tenía el problema.
  - Pulsómetro: si no se ve la banda, el Panel ya dice qué comprobar (que esté puesta y humedecida, y que no esté conectada a un reloj, al móvil o a Zwift) y la terminal lo escribe una vez. Antes solo ponía «WAITING».
- **Entrenamientos estructurados sin ERG** (`coach/workouts/structured.py`, página **Entrenamientos**):
  - Bloques (calentamiento, trabajo, recuperación, vuelta a la calma) con un objetivo de vatios en % de tu FTP, constante o en rampa, y una cadencia sugerida. Tú alcanzas el objetivo con las marchas: nunca se manda potencia al rodillo.
  - FTP del perfil o, si no hay, el estimado con tu historial. Sin ninguno, la página pide hacer el test.
  - Biblioteca pensada para maratones de BTT: recuperación activa, tempo 2×20, sweet spot 3×12, umbral 2×15, VO2 máx 5×4, subidas a baja cadencia 5×6 y cambios de ritmo 3×9. Cada uno con su duración, IF y TSS previstos y un gráfico de bloques coloreado por zonas.
  - Panel: objetivo, potencia de 3 s (verde en el objetivo, naranja fuera de ±10 %), tiempo que queda del bloque, cadencia, el siguiente bloque y el entrenamiento entero con tu posición. La gráfica de potencia dibuja el objetivo en discontinua (también en replay).
  - Empezar un entrenamiento inicia una sesión; «Pausar» la sesión pausa el entrenamiento; terminar la sesión lo termina.
  - Cada bloque se puntúa: cumplimiento (potencia media frente al objetivo medio) y tiempo en rango (±10 %). Sin datos cuenta como 0 W.
  - El resumen de la sesión guarda el entrenamiento y sus bloques (también el test de FTP); el CSV, el objetivo de cada segundo (`targetPowerW`). En Sesiones e Historial la sesión lleva el nombre del entrenamiento.
  - API: `GET /workout/library`, `POST /workout/structured/start`; reenvío en la API Java.
  - En el simulador, el ciclista simulado sigue el objetivo y la cadencia de cada bloque (hasta 260 W).
- **Repaso visual de la interfaz** (capturas del 16-11):
  - Panel: barra de estado en español (Conectado, Buscando…) con el motivo en un ⓘ; no muestra el pulsómetro ni los mandos si están desactivados. Sin sesión no aparecen las estadísticas vacías. La tarjeta de pendiente ya no va resaltada y dice «llano · sin elegir» hasta que eliges una.
  - Gráficas: el perfil de altitud solo sale si hay desnivel (≥ 2 m), la de pendiente solo si cambia, y la de pulso solo si hay pulsómetro.
  - Rutas: cada ruta lleva una miniatura de su perfil (`thumb` en `GET /routes`) y un botón «Perfil grande / Perfil pequeño». La nota de las bajadas sale una vez arriba, no en cada ruta.
  - Sesiones: las de prueba (menos de 1 minuto o sin trabajo) se ocultan tras «Mostrar N sesiones de prueba». IF y TSS usan el FTP estimado del historial cuando el perfil no tiene FTP, igual que la página Historial. Botones del mismo tamaño.
  - Historial: la tabla muestra 30 actividades y «Ver más» (antes, las 122 seguidas).
  - **Nada se mueve sin pedirlo**: el ciclista simulado solo pedalea con una sesión en marcha (antes pedaleaba siempre y parecía que había una sesión), y un replay espera en 0:00 a «Reproducir». Sin sesión, el Panel deja los números vacíos y en vez de gráficas dice «Sin sesión»; tras «Terminar» se quedan las gráficas de la última sesión.
  - Menos texto: las explicaciones (marchas, pendiente, test de FTP, rutas, perfil, dispositivos) van plegadas en «ⓘ ¿Cómo funciona?». Títulos más pequeños.
  - Las etiquetas de los ejes ya no se cortan en los bordes («0 min», «10 min»).
  - Rutas: miniatura de un solo color (los colores por pendiente, en el perfil grande); sin el nombre del fichero.
  - Sesiones: «Ver en replay» y «Descargar FIT» a la vista, el resto de descargas en «Más ▾»; el tiempo por marcha es una minigráfica de barras; «FTP estimado» pasa a «FTP de esta sesión».
  - Ajustes: el perfil del ciclista va primero; identificadores Bluetooth abreviados (el completo al pasar el ratón); «Volver a .env» pasa a «Restaurar valores por defecto» (no toca el perfil).
- **Forma, fatiga y frescura** (`coach/history/load.py`, sección en Historial):
  - Carga de cada actividad en unidades TSS:
    - **con potencia** (bici, si hay FTP): horas × IF² × 100;
    - **con pulso**: TRIMP de Banister segundo a segundo, escalado a 100 por hora en el umbral;
    - **sin nada**: estimación por duración, marcada como tal.
  - Forma (CTL, 42 días), fatiga (ATL, 7 días) y frescura (TSB, la de ayer), con su interpretación.
  - Umbrales del perfil (nuevos campos opcionales de pulso en reposo, máximo y umbral). Si faltan, se estiman: FTP = 95 % del mejor tramo de 20 minutos del último año; pulso máximo del historial, descartando un pico suelto (en los datos reales, 195 frente a 181); umbral = 90 % del máximo. Siempre se indica de dónde sale cada uno.
  - Las actividades grabadas dos veces cuentan una sola vez (2 en los datos reales: una salida de Zwift grabada también como «bici»).
  - Validado con el «Esfuerzo relativo» de Strava en 57 actividades con pulso: correlación 1,00 (rangos 0,95); bici 1,00, fuerza 0,96, carrera 0,93.
  - Corregido por el camino:
    - la app de Strava graba el pulso cada 5 s, y la regla de huecos de la potencia (3 s) tiraba el 75 % de esos datos; ahora el pulso se arrastra hasta 30 s;
    - una actividad con el pulso grabado 15 h más allá de su final ahora solo cuenta su parte.
  - API `GET /history/load`.
- **Test de FTP (rampa, sin ERG)** (`coach/workouts/ramp_test.py`, panel «Test de FTP» en el Panel):
  - Protocolo: 5 minutos suaves y luego escalones de 1 minuto desde 100 W (o el 40 % de tu FTP), +20 W por minuto. El objetivo se alcanza con las marchas; termina al dejar de pedalear 5 s o con «He terminado».
  - FTP = 75 % del mejor minuto de la rampa. Si la rampa dura menos de 3 minutos, no se da resultado.
  - «Guardar como mi FTP» lo pasa al perfil, y desde ahí se calculan IF y TSS (sesiones y FIT).
  - Se graba como sesión. No manda nada al rodillo: solo lee la telemetría.
  - En el simulador, un ciclista simulado sigue el objetivo hasta 260 W, para probarlo sin rodillo.
  - API `POST /workout/ramp/start`, `/workout/stop`, `/workout/ftp/save` y `/workout/clear`.
- **Historial de actividades** (`coach/history/`, página **Historial**, guía `docs/IMPORTAR-historial.md`):
  - Junta las sesiones de la aplicación (entran solas) con lo importado de una **exportación de Strava** (`tools/import_strava.py`, leída directamente del ZIP). Se guarda en SQLite en la carpeta de datos, con copia de los ficheros originales. Reimportar no duplica.
  - **Lector de FIT propio**, sin dependencias. Contempla cabeceras comprimidas, big endian, campos de desarrollador, ficheros encadenados y valores inválidos. Con las 112 actividades FIT de una exportación real: 109 idénticas al decodificador oficial de Garmin, y en las otras 3 nuestro lector trata como «sin dato» una altitud 0xFFFF que el oficial convierte en 12 607 m.
  - Con esa exportación real, frente a las cifras de Strava: distancia ±0,01 %, tiempo en movimiento (mediana 0 %), pulso medio −0,2 ppm, potencia media −0,4 W en salidas virtuales. NP +4,6 W de mediana frente a la «potencia ponderada» de Strava (un cálculo propio de Strava, no publicado; probadas cinco variantes y ninguna lo explica). Nuestra NP es la de Coggan.
  - Página con horas por semana por tipo (bici, rodillo, carrera, fuerza…) y la lista de actividades. API `GET /history` y `/history/weeks`, con reenvío en la API Java.
- **Desnivel de las rutas, decidido con datos reales** (tarea 8): la altitud se suaviza con una media de 50 m (antes 100). Con tres maratones de BTT exportadas de Strava, nuestro desnivel queda a −0,2 %, +0,4 % y +0,8 % del que muestra Strava; con 100 m quedaba un 4–5 % por debajo. Los métodos con umbral (Serpentine y GoldenCheetah) daban entre −9 y −14 %, y gpxpy entre +5 y +7 %. La pendiente sigue con el método de Serpentine.
- **Tipo de bici en el perfil: carretera o BTT** (`virtual_ride.BIKE_PHYSICS`). Cambia la física de la carretera virtual (CdA y rodadura) y la rodadura que se manda al rodillo.
  - Carretera: CdA 0,40 y Crr 0,004 (validados con el rodillo).
  - BTT: CdA 0,55 y Crr 0,010. Es una estimación sin validar: Incyclist usa cwA 0,57 para BTT, y la rodadura medida en tierra y grava está entre 0,008 y 0,015.
  - Con 200 W y 90 kg: 27 km/h en llano en BTT frente a 32 en carretera; al 8 %, 8,9 frente a 9,6.
  - El guardián del rodillo solo admite esas dos rodaduras.
- **Rutas de BTT**:
  - Pendientes admitidas hasta ±30 %. Antes se recortaban a −15 … +20 %, y una maratón real con bajadas del −22 % salía con 280 «tramos imposibles» que eran reales. En el rodillo, las bajadas siguen limitadas por tu límite de bajada.
  - GPX de hasta 50 MB (antes 10), leídos por streaming.
  - Si un fichero es demasiado grande, el error dice su tamaño y el máximo; antes se cortaba la conexión con un «Invalid request size».
- **Exportar sesiones a FIT** (`coach/session/fit_export.py`, botón «Descargar FIT» en Sesiones), para intervals.icu, Strava, GoldenCheetah, TrainingPeaks…
  - Codificador FIT propio, sin dependencias. Los números de mensaje y de campo, las escalas y las enumeraciones se sacaron del perfil oficial (FIT SDK 21.171).
  - Registros a 1 Hz con potencia, cadencia, pulso, velocidad y distancia de la carretera virtual, altitud y pendiente. Las pausas son eventos de cronómetro y los cortes de datos se marcan como inválidos, sin inventar valores. Vuelta y sesión con tiempo, distancia, trabajo, potencia media y máxima, NP, IF, TSS, FTP, desnivel, pulso y cadencia. Deporte: ciclismo, actividad virtual.
  - Validado con las herramientas de Garmin sobre una sesión real: los 25 tests de verificación de FitCSVTool, la comprobación de integridad y el decodificador oficial de Python, que lee exactamente los valores de la sesión. Los tests lo comprueban con un lector propio y, si existe `FIT_SDK_DIR`, también con la verificación oficial (con pausas y cortes).
  - Guía para validar las métricas en intervals.icu: `docs/pruebas/VALIDAR-metricas-intervals.md`.
- **Pendiente de las rutas GPX con el método de Serpentine** (MIT): media de ±30 m aplicada 3 veces y pendiente calculada sobre 40 m, con un perfil cada 5 m (antes 10 m). Comparado con otros proyectos (Serpentine, qdomyos-zwift, gpxpy, GoldenCheetah) sobre rutas sintéticas: los picos falsos en un llano con ruido de GPS bajan de 2,1 % a 1,3 %, una rampa real de 1→5 % conserva su forma (70 m en vez de 80) y la subida media no cambia. Contrapartida: un repecho corto de 2 % se nota como 1,4 % (antes 1,6). El desnivel acumulado no cambia: ningún método fue mejor a la vez con ruido y con repechos reales, y se decidirá con GPX reales (`docs/PENDIENTES-sin-rodillo.md`).
- **Panel de pendiente más claro**: muestra el progreso hacia lo pedido («Carretera 4,9 % → 7,5 % · faltan ~52 m»), avisa al parar («al volver a pedalear seguirá hacia 7,5 %») e indica la dificultad junto a la pendiente del rodillo.
- **Modelo de velocidad contrastado con Incyclist** (MIT): misma ecuación y mismas velocidades en subida. En llano vamos ~5 % más despacio porque usamos CdA 0,40 (validado con el rodillo) en vez de su 0,35 de ciclista medio.
- **Rutas GPX** (`coach/session/route.py`, `coach/app/routes_store.py`, página **Rutas**):
  - Subir GPX (1.0 o 1.1, con track o ruta, y con altitud; máximo 10 MB), guardarlos en `ai-cycling-coach-data/routes/` (fuera del repositorio) sin sobrescribir nunca, ver su perfil y elegir cuál rodar. Funciona en el simulador y en el rodillo real con el control de marchas.
  - Perfil cada 10 m. La altitud de los GPX es ruidosa y se suaviza con una media de 100 m: con ±1,5 m de ruido, un llano quedaba con picos del 5,5 % usando 50 m y queda por debajo del 3 % con 100 m. Los extremos se tratan por reflexión, para no aplanar una ruta que empieza o termina subiendo. Las pendientes imposibles se recortan a −15 … +20 % y se avisa.
  - Mientras ruedas una ruta, la pendiente pedida es la del perfil en la distancia recorrida desde que empezó, con la transición de siempre (1 % cada 20 m). Al final pasa a llano. La pendiente manual queda bloqueada hasta salir de la ruta, y al salir se mantiene la pendiente del momento, sin saltos.
  - Panel: perfil completo de la ruta con tu posición y los kilómetros que quedan. El CSV de sesión guarda `routeName` y `routeProgressKm`.
  - API: `GET/POST /routes`, `GET /routes/<fichero>` (perfil), `GET /route`, `POST /route/start` y `POST /route/stop`; reenvío en la API Java.
  - Corregido en las pruebas: un último tramo de pocos centímetros generaba una pendiente absurda al final de la ruta.
  - Rutas sin el rodillo: `docs/PENDIENTES-sin-rodillo.md`.
- **Proyecto open source (MIT)**:
  - `LICENSE` (MIT) y `THIRD_PARTY_NOTICES.md`: el código del protocolo Zwift portado de Serpentine (MIT) con su aviso, y créditos de Incyclist, jat255 y de los proyectos consultados solo como referencia (BikeControl, qdomyos, SHIFTR, zwiftplay).
  - `scripts/mask_personal_data.py`: cambia los identificadores Bluetooth reales, números de serie y nombres de dispositivos cercanos por valores falsos fijos, y los pesos de las guías por pesos de ejemplo. Aplicado a fixtures, tests y guías; los tests usan ahora 80 + 9,5 kg.
  - `scripts/init-git-repo.sh` y `scripts/clean-git-history.sh`: crear el repositorio y, antes de publicar, dejar el historial en dos commits limpios (v4.2.2 y v4.3.0) con el correo noreply de GitHub. Guía: `docs/GIT-crear-repositorio.md`.
- **Gráficas**:
  - Nuevo **perfil del recorrido**: altitud según la distancia, coloreada por pendiente, con el desnivel acumulado.
  - La gráfica de pendiente dibuja las **bajadas** (antes se salían por debajo), con una rejilla que se adapta a cualquier valor (antes el eje empezaba en 0 y tenía una escala mínima de 4 %), y la pendiente del rodillo en discontinua.
  - Nueva gráfica de **velocidad**.
  - Las grabaciones antiguas siguen mostrándose como antes (pendiente ordenada contra el tiempo).

### Organización del proyecto
- Un solo `README.md` (cómo arrancar y estructura) y este `CHANGELOG.md` con las notas de cada versión.
- `docs/adr` (decisiones), `docs/pruebas` (guías que ejecutas tú), `docs/blog`.
- `trainer-adapter/` organizado en el paquete `coach/` (`app`, `bluetooth`, `devices`, `session`), `tools/` (diagnóstico, solo lectura) y `tests/` (con `tests/fixtures`). El punto de entrada sigue siendo `trainer-adapter/server.py`.
- **Tus datos salen de las carpetas de versión**: grabaciones, dispositivos, ajustes y perfil viven en `~/.ai-cycling-coach/` (`AI_COACH_HOME`). `init.sh` copia (sin sobrescribir ni borrar) las grabaciones de la carpeta del proyecto. Un `REPLAY_FILE` antiguo (`trainer-adapter/recordings/x.csv`) se sigue encontrando por nombre.

Versión completa en carpeta propia; no sobrescribe la v4.2.2. Deja fino lo que ya existía (fase 0) y añade el autodescubrimiento Bluetooth (fase 1). Sigue sin control físico desde los mandos.

### Cambios

- **Un único bucle Bluetooth** (`trainer-adapter/ble_runtime.py`). Rodillo, pulsómetro y los dos mandos Zwift son ahora tareas de un mismo bucle asyncio en un único hilo, en vez de un hilo y un bucle por dispositivo. Los escaneos van de uno en uno (lock compartido) y cada mando busca solo su dirección en lugar de un escaneo completo de 8 s. Objetivo: menos SEARCHING/NOT_FOUND intermitentes en macOS.
- **Parada inmediata**: las esperas de reconexión (hasta 15 s) se interrumpen al parar. La parada sigue esperando hasta 8 s a que el rodillo vuelva a 0 % si había control activo.
- **`server.py` sin variables globales**: el estado va en `AdapterState` y el servidor se crea con `make_server()`. Las rutas ignoran la query string (`/telemetry?x=1`).
- **Tests de los endpoints HTTP** contra un servidor real: REPLAY, SIMULATOR y WAHOO; códigos 404, 409 y 400.
- **`.env.example` limpio**: cada clave una sola vez y mandos Zwift desactivados y sin identificadores. Tu `.env` no se toca.
- **Versión única** en el fichero `VERSION`; la cabecera de la web la lee de ahí.
- **Proxy Java**: pasa el JSON de Python tal cual (no pierde campos) y conserva su código de error; «adapter offline» (503) solo si no hay conexión. Nuevos `GET /api/trainer/replay/state` y `/api/trainer/devices`.

### Página de Ajustes (nueva) y frontend

- **Ajustes** (`http://127.0.0.1:5173/#/ajustes`): elegir fuente de datos (Rodillo real, Replay, Simulador), la grabación del replay, **subir un CSV**, activar pulsómetro y mandos, y la grabación en modo rodillo. Se aplica **al momento, sin reiniciar**.
- Lo que guardas desde Ajustes va a `~/.ai-cycling-coach/settings.json` (fuera de las carpetas de versión) y manda sobre `.env`; «Volver a .env» lo borra. Puertos, identificadores y el control físico experimental siguen solo en `.env`: con `CONTROL_TEST_ENABLED=true` la página no deja cambiar nada.
- Un cambio inválido (fichero que no existe, CSV roto) se rechaza sin tocar lo que está funcionando. Los CSV subidos se validan y nunca sobrescriben otro.
- Se ven y se pueden **olvidar** los dispositivos recordados.
- **Perfil del ciclista** (también en Ajustes): peso del ciclista, peso de la bici, FTP opcional y transmisión (Zwift Cog o cassette). Se guarda en `~/.ai-cycling-coach/profile.json`; los valores fuera de rango se rechazan (no se recortan). Lo usarán la simulación, los límites de seguridad y las métricas.
- El panel se ha reescrito por componentes (`frontend/src/components`, `pages`, `api.ts`, `hooks.ts`) y corrige: eje de tiempo y leyenda que solo valían para 10 minutos, botón «Ir al minuto 5» (ahora «Ir a la primera orden»), 24 marchas fijas, línea de tiempo que enviaba una petición por cada píxel (ahora al soltar), errores que mostraban HTML de Python, reintentos sin espera cuando el adaptador no responde, batería de los mandos en la cabecera.

### Autodescubrimiento (docs/adr/ADR-002-autodiscovery.md)

- Ya no hace falta poner identificadores en `.env`: rodillo, pulsómetro y mandos se encuentran por lo que anuncian (FTMS, Heart Rate, servicio/fabricante Zwift) y se recuerdan en `~/.ai-cycling-coach/devices.json`, fuera de las carpetas de versión.
- Orden por rol: ID de `.env` si existe (nunca se sustituye por otro) > dispositivo recordado > escaneo.
- Izquierdo/derecho: por el byte de tipo del anuncio; si no viene, por la primera pulsación, que se recuerda.
- Batería de los mandos en la telemetría (`zwiftLeftBatteryPercent`, `zwiftRightBatteryPercent`).
- `GET /devices` muestra lo recordado.
- Herramienta de diagnóstico, solo lectura: `trainer-adapter/.venv/bin/python trainer-adapter/tools/discovery.py --seconds 15` lista lo que hay alrededor y guarda los anuncios en `~/.ai-cycling-coach/recordings/ble_scan_*.json`; con `--remember` guarda lo que no sea ambiguo.

### Verificado en el entorno de creación

- 93 pruebas unitarias de Python: OK (incluye autodescubrimiento con paquetes y escaneo reales de tus mandos, y la parte de Ajustes: cambio de modo en caliente, subida de CSV, validaciones).
- Prueba de extremo a extremo Python + Java (lanzado sin Maven) con las llamadas de la web: telemetría, subir CSV, cambiar a ese replay, a simulador, errores 409/400, volver a .env, dispositivos: OK.
- `npm run build`: OK.
- Backend Java: compila (javac); sus 13 tests nuevos no se han podido ejecutar aquí → `cd backend && mvn test`.
- `npm run build` del frontend: OK; la cabecera muestra v4.3.0.
- **No verificado**: tests Java y todo lo que necesita dispositivos BLE reales.

### Pendiente de probar en el Mac

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
bash init.sh --start
```

0. `cd backend && mvn test` y `trainer-adapter/.venv/bin/python trainer-adapter/tools/discovery.py --seconds 15` (pulsa un botón de cada mando durante el escaneo). Pásame el `ble_scan_*.json` (en `~/.ai-cycling-coach/recordings`).
1. REPLAY: reproducir, pausar, saltar (arrastrando la línea de tiempo) y cambiar marcha virtual.
1b. Ajustes: subir un CSV, elegirlo, «Aplicar» y volver al Panel; cambiar a Simulador y de nuevo a Replay; «Volver a .env».
2. Con `ZWIFT_ENABLED=true` y **sin** `ZWIFT_*_DEVICE_ID` en `.env`: los dos mandos deben encontrarse solos, pasar a CONNECTED y mantenerse estables; pulsa + y − y revisa `~/.ai-cycling-coach/devices.json`.
3. Con `TRAINER_MODE=WAHOO` y `HR_ENABLED=true`: rodillo, pulsómetro y mandos conectados a la vez.
4. Ctrl+C: todo se detiene en pocos segundos.


## AI Cycling Coach v4.2.2 — Perfil FTMS exacto

Se revierte el suavizado visual de la pendiente de v4.2.1. La gráfica de REPLAY vuelve a mostrar exclusivamente **escalones** correspondientes a las órdenes FTMS registradas en la sesión: 1 %, 2 %, 3 %, 2 %, 0 %. Antes de la primera orden se muestra un intervalo desconocido, NO se inventa 0 %.

Se conservan sin modificaciones la grabación CSV, los gráficos progresivos, los controles Java/Python corregidos y la configuración de mandos de v4.2.1. Las marchas de REPLAY son virtuales; no modifican físicamente el KICKR. El perfil no es altitud medida ni control físico.

Instalación en carpeta independiente:

```sh
cd ~/dev/ai-cycling-coach-v4.2.2
bash init.sh --start
```

Este paquete NO ha sido compilado completamente ni probado con mandos BLE reales en el entorno de creación. Validar mediante `npm run build` en frontend y con los controles de REPLAY en el Mac.


## AI Cycling Coach v4.2.1 — Mandos y perfil redondeado

Esta versión completa habilita la lectura de los dos mandos Zwift registrados para este Mac en `.env` y `.env.example`. En modo `REPLAY` las pulsaciones `+` y `−` deben modificar **únicamente** la marcha visual de 1 a 24. No altera la velocidad medida ni manda resistencia al KICKR. Comprueba el estado CONNECTED de ambos mandos en la cabecera. Si otros programas tienen conectados los mandos, desconéctalos antes.

La gráfica del perfil tiene ahora una curva continua ilustrativa mediante suavizado amplio (aproximadamente 34 segundos de escala gaussiana). No representa altitud GPS ni cambia los valores de pendientes ordenadas. Los primeros cinco minutos siguen etiquetados como *sin orden registrada*, no como 0 %. Un checkbox permite mostrar u ocultar los **escalones reales de las órdenes FTMS**, que no se modifican.

### Instalar

Descomprime en `~/dev/ai-cycling-coach-v4.2.1`, detén la instancia anterior, y ejecuta:

```bash
cd ~/dev/ai-cycling-coach-v4.2.1
bash init.sh --start
```

Las identificaciones BLE están fijadas a los UUID conocidos de este Mac. Si se usan otros mandos u otro Mac hay que actualizar `.env`. Para desconectar los mandos, cambia `ZWIFT_ENABLED=false`. Los puertos existentes deben estar libres.

### Prueba rápida

1. Cabecera: Zwift izquierdo y derecho deben mostrar CONNECTED. Si figura SEARCHING, NOT_FOUND o ERROR, mira la terminal del adaptador.
2. Pulsa el botón físico `+` derecho y observa incremento visual de marcha 12 a 13 (o desde la marcha actual). Pulsa `−` izquierdo para bajar. El campo «Último botón» debe cambiar.
3. En la sección Perfil, desmarca «Ver órdenes FTMS exactas» para ver solo la curva, o márcalo para superponer los escalones reales de la grabación.

En ningún caso se envían comandos físicos de control FTMS desde REPLAY.


## AI Cycling Coach v4.2 — Visualización progresiva y perfil suavizado

Versión **completa**, autocontenida. Instala en carpeta nueva `~/dev/ai-cycling-coach-v4.2`, **sin fusionar** con v4.1. Los archivos reales de 10 minutos están incluidos en `trainer-adapter/recordings/` y se conservan los originales.

### Novedades

- REPLAY: las curvas de potencia, frecuencia cardíaca y cadencia **crecen con el tiempo reproducido**. Alterna **Durante la sesión** / **Análisis completo** para consultar la sesión entera sin esperar.
- Pendiente: silueta suavizada **solo estética**, más línea discontinua escalonada con la **orden FTMS original**. La tarjeta muestra el valor original exacto; los primeros cinco minutos se mantienen como *sin orden registrada*, no 0 %.
- Cursor de reproducción sobre todas las gráficas. Potencia instantánea y media móvil de 3 segundos siguen visibles.
- Botones de reproducción y marcha virtual como en v4.1. **Incorporada la corrección del controlador Java para POST de JSON con longitud conocida**. Si hay errores upstream, el backend devuelve datos diagnósticos.
- **Ningún control físico de marchas:** las 24 relaciones son ilustrativas. Modo REPLAY no envía instrucciones al KICKR. El perfil no es una elevación GPX medida.

### Instalación en Mac

1. Descomprime como carpeta nueva `~/dev/ai-cycling-coach-v4.2`. No reemplaces la v4.1.
2. Importa solo grabaciones adicionales, si las hay, sin sobrescribir las incluidas:

   ```bash
   cp -n ~/dev/ai-cycling-coach-v4.1/trainer-adapter/recordings/* ~/dev/ai-cycling-coach-v4.2/trainer-adapter/recordings/ 2>/dev/null || true
   ```
3. Arranca la instalación automática:

   ```bash
   cd ~/dev/ai-cycling-coach-v4.2
   bash init.sh --start
   ```

4. Abre `http://127.0.0.1:5173`. Si otro proyecto usa los puertos 5173, 8081 o 8766, detén antes sus procesos con Ctrl+C. El `.env` incluido usa `TRAINER_MODE=REPLAY`, `CONTROL_TEST_ENABLED=false` y `ZWIFT_ENABLED=false`.

### Comprobaciones locales realizadas

- Python: **31 pruebas unitarias superadas**.
- TypeScript TSX: **análisis sintáctico sin errores** por TypeScript global.
- Scripts bash: análisis sintáctico correcto.
- **No se ha podido ejecutar `npm install` ni compilar React contra sus dependencias** en este entorno porque no están en caché y no hay acceso al registro de npm. Se realizará en tu Mac con `init.sh`.
- **No se ha recompilado Java en este entorno** (Maven no está disponible aquí); `init.sh` recompila el backend en tu Mac.


## AI Cycling Coach v4.1 — Dashboard, Replay y marchas virtuales (sin control físico)

Versión **completa**, no parche. No sobrescribir v4 ni v2.

### Instalación en Mac

1. Descomprimir el ZIP en `~/dev/` como `ai-cycling-coach-v4.1/`.
2. Conservar las carpetas de versiones anteriores, en especial las grabaciones.
3. Copiar recordings adicionales sin sobrescribir archivos existentes:

   ```bash
   cp -n ~/dev/ai-cycling-coach-v4/trainer-adapter/recordings/* \
     ~/dev/ai-cycling-coach-v4.1/trainer-adapter/recordings/ 2>/dev/null || true
   ```

4. Usar `.env` incluido. `TRAINER_MODE=REPLAY`, `CONTROL_TEST_ENABLED=false`, `ZWIFT_ENABLED=false`.
5. Arrancar:

   ```bash
   cd ~/dev/ai-cycling-coach-v4.1
   chmod +x start.sh scripts/*.sh
   python3 -m venv trainer-adapter/.venv
   trainer-adapter/.venv/bin/python -m pip install -r trainer-adapter/requirements.txt
   ./start.sh
   ```

6. Abrir `http://127.0.0.1:5173`.

**REPLAY no conecta al rodillo ni envía órdenes FTMS.** En el modo replay los botones de UI cambian solo la marcha virtual representada (1–24); modelo de relación relativa *ilustrativo*, no replica la tabla de Zwift ni se traduce a resistencia. Para usar los dos mandos físicos en modo visual, activar `ZWIFT_ENABLED=true` y configurar sus identificadores, sin otras órdenes al KICKR.

### Novedades

- Endpoint Python `/replay/session`: 600 registros íntegros para los gráficos, sin depender de cuándo se abra React.
- Endpoint Python `POST /replay/control`: `play`, `pause`, `restart`, `seek` y `speed` (0.5, 1, 2, 4).
- Endpoint Python `POST /replay/gear`: cambios visuales +1/-1, únicamente en modo REPLAY.
- API Spring Boot reenvía los tres endpoints bajo `/api/trainer/replay/...`.
- React: perfil de pendiente ordenada con tramo desconocido, línea temporal, reproductor, gráficos de potencia/pulso/cadencia de sesión completa, potencia suavizada tres segundos, estadísticas y marchas virtuales.
- Control del Wahoo sin cambios desde v4. No se ha habilitado el cambio físico. No se repite automáticamente el experimento de pendientes mientras REPLAY esté activo.

### Verificación realizada

- 31 pruebas unitarias de Python: OK.
- Prueba HTTP real de `/health`, `/replay/session`, pausa, salto al segundo 420, lectura de pendiente (2 %) y cambio virtual al 13: OK.
- Parseo TypeScript/TSX con compilador TypeScript global: sin errores sintácticos.
- **Pendiente de probar en tu Mac:** `npm install` y `npm run build` para verificar dependencias y compilación completa; prueba end-to-end React + Java.

### Si algo falla

```bash
cd ~/dev/ai-cycling-coach-v4.1/frontend
npm install
npm run build
```

Comparte el error exacto antes de modificar archivos. Mantén las grabaciones y `.env` de versiones antiguas intactos.


## AI Cycling Coach v4 — proyecto completo

Una versión **completa y autocontenida** con backend Spring Boot (Java 21), frontend React/TypeScript (Vite), adaptador Python BLE, grabaciones y modo REPLAY. No aplicar sobre v2: **extraer en una carpeta nueva**.

### Instalación en Mac

1. Descomprime la carpeta `ai-cycling-coach-v4` en `~/dev/`. No borres `~/dev/ai-cycling-coachV2`.
2. `cd ~/dev/ai-cycling-coach-v4`
3. Para traer **todas** tus grabaciones de v2 sin sobrescribir las incluidas: `./scripts/import-v2-recordings.sh`. Puedes indicar otra ruta v2 como primer argumento.
4. Instala el adaptador: `python3 -m venv trainer-adapter/.venv && trainer-adapter/.venv/bin/python -m pip install -r trainer-adapter/requirements.txt`
5. Ejecuta `./start.sh` (requiere Java 21, Maven, Node y npm).
6. Abre `http://127.0.0.1:5173`. Por defecto usa el CSV real de 10 minutos incluido en `trainer-adapter/recordings`.

### Modo grabación física

En `.env` cambia `TRAINER_MODE=WAHOO`, `RECORD_ENABLED=true`, `HR_ENABLED=true`. **Deja `CONTROL_TEST_ENABLED=false`** salvo que quieras ejecutar expresamente un nuevo experimento físico controlado. `ZWIFT_ENABLED=true` conecta los mandos si configuras sus IDs; las marchas siguen siendo **solo visuales** y no envían cambios al rodillo.

### Qué está probado y qué falta

- Incluye la sesión CSV/JSONL de referencia que compartiste, más scripts de diagnóstico.
- La conexión BLE a Wahoo, HR50 y mandos fue confirmada anteriormente por ti con otras versiones.
- Esta reconstrucción v4 se valida aquí mediante las pruebas Python y comprobaciones de integridad; la prueba completa Java/React en tu Mac debe confirmarse allí.
- La pendiente mostrada es **pendiente ordenada** al rodillo, no medida físicamente; durante los primeros 5 minutos puede aparecer «—».
- Todavía **no** hay cambio de marchas físico desde Zwift Click.

### Seguridad de las grabaciones

No borres v2. El script importa solo archivos que no existan ya en v4, sin modificar origen. Haz copia externa de `trainer-adapter/recordings` antes de nuevas sesiones importantes. `.env` y datos privados quedan fuera de repositorios Git según `.gitignore`.
