# AI Cycling Coach

Panel de entrenamiento local para rodillo inteligente (Wahoo KICKR CORE 2), pulsómetro y mandos Zwift.
Todo funciona en tu ordenador (`127.0.0.1`); ningún dato sale de él.

Versión actual: ver `VERSION`. Novedades de cada versión: `CHANGELOG.md`.

## Arrancar

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
bash init.sh --start
```

`init.sh` comprueba Python, Node, Java y Maven, prepara dependencias, compila y arranca. Las siguientes veces basta con `./start.sh`.

`./start.sh` compila la interfaz y el API Java solo cuando han cambiado, y los sirve optimizados: cada página abre
rápido también la primera vez. Para desarrollar, `./start.sh --dev` (Vite compila cada página al abrirla y los cambios
se ven sin reiniciar).

Abre `http://127.0.0.1:5173`. En el **Panel** inicias, pausas y terminas las sesiones; en **Sesiones** las ves, descargas y reproduces. En **Ajustes** eliges la fuente de datos (rodillo real, replay o simulador), subes grabaciones, activas pulsómetro y mandos, y rellenas tu perfil.

La aplicación lleva una **carretera virtual**: la velocidad se calcula con física a partir de tus vatios y tu peso (la del rodillo no baja al subir), y con ella la distancia, la altitud y el desnivel acumulado. La pendiente la eliges tú y cambia según avanzas, como en una carretera. Puedes probarla sin rodillo en el simulador: `docs/pruebas/PRUEBA-pendiente-en-el-simulador.md`.

En **Sesiones** puedes descargar cada entrenamiento en **FIT** para subirlo a intervals.icu, Strava o GoldenCheetah.

En **Rutas** subes el GPX de una carrera o de un puerto y lo ruedas: la pendiente sigue su perfil según avanzas, y el Panel muestra el recorrido completo con tu posición.

## Tus datos

En `~/dev/ai-cycling-coach-data/`, **junto a** las carpetas de versión: cada versión nueva los encuentra sin copiar nada, y se pueden compartir para analizarlos. Lo que hubiera en el antiguo `~/.ai-cycling-coach/` se copia allí al arrancar (sin sobrescribir ni borrar). Otra carpeta: `AI_COACH_HOME` en `.env`.

| Qué | Dónde |
|---|---|
| Sesiones (CSV + resumen + captura opcional) y grabaciones para replay | `ai-cycling-coach-data/recordings/` |
| Resultados de las herramientas de diagnóstico (para compartirlos) | `diagnostics/` dentro del proyecto |
| Dispositivos recordados | `ai-cycling-coach-data/devices.json` |
| Ajustes guardados desde la web | `ai-cycling-coach-data/settings.json` |
| Perfil del ciclista | `ai-cycling-coach-data/profile.json` |
| Rutas GPX subidas | `ai-cycling-coach-data/routes/` (`ROUTES_DIR` para otra carpeta) |

`.env` da los valores por defecto (copia de `.env.example` en la primera instalación). Lo guardado en Ajustes manda sobre `.env` hasta que pulses «Volver a .env».

## Estructura

```
├── README.md  CHANGELOG.md  VERSION
├── init.sh  start.sh  .env.example
├── scripts/            utilidades de shell (carga de .env, comprobaciones, importar grabaciones)
├── docs/
│   ├── adr/            decisiones de arquitectura
│   ├── pruebas/        guías paso a paso para probar con el hardware
│   └── blog/
├── frontend/           React + TypeScript (Vite)
│   └── src/            api.ts, hooks.ts, types.ts, format.ts, components/, pages/
├── backend/            Java 21 + Spring Boot: API /api/trainer/** que reenvía al adaptador
└── trainer-adapter/    Python + Bleak: Bluetooth, replay, grabación
    ├── server.py       punto de entrada
    ├── coach/
    │   ├── app/        servidor HTTP, runtime (cambio de modo en caliente), ajustes, perfil, grabaciones
    │   ├── bluetooth/  bucle BLE único, autodescubrimiento, búsqueda y registro de dispositivos
    │   ├── devices/    rodillo (FTMS), pulsómetro, mandos Zwift
    │   └── session/    grabación CSV, replay, captura en bruto, marchas virtuales
    ├── tools/          diagnóstico de solo lectura (discovery.py, trainer_probe.py, sondas antiguas de mandos)
    └── tests/          pruebas unitarias (fixtures: paquetes reales grabados)
```

## Pruebas

```sh
cd trainer-adapter && .venv/bin/python -m unittest discover -s tests -t .
cd backend && mvn test
cd frontend && npm run build
```

## Herramientas de diagnóstico (no envían nada a los dispositivos)

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/discovery.py --seconds 15     # qué hay alrededor
trainer-adapter/.venv/bin/python trainer-adapter/tools/trainer_probe.py --seconds 15 # inventario del rodillo
```

Los resultados se guardan en la carpeta `diagnostics/` del proyecto (para compartirlos). Guías completas en `docs/pruebas/`.

## Seguridad

No hay control físico del rodillo salvo el experimento supervisado `CONTROL_TEST_ENABLED` (solo en `.env`, desactivado por defecto). Las marchas virtuales actuales son solo visuales.

## Licencia

MIT (`LICENSE`). Parte del protocolo Zwift está portada de Serpentine (MIT); los créditos y las licencias de los
proyectos de los que aprendimos están en `THIRD_PARTY_NOTICES.md`.

Antes de añadir grabaciones nuevas a `tests/fixtures`, enmascara los identificadores de tus dispositivos:
`python3 scripts/mask_personal_data.py`.
