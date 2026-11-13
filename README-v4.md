# AI Cycling Coach v4 — proyecto completo

Una versión **completa y autocontenida** con backend Spring Boot (Java 21), frontend React/TypeScript (Vite), adaptador Python BLE, grabaciones y modo REPLAY. No aplicar sobre v2: **extraer en una carpeta nueva**.

## Instalación en Mac

1. Descomprime la carpeta `ai-cycling-coach-v4` en `~/dev/`. No borres `~/dev/ai-cycling-coachV2`.
2. `cd ~/dev/ai-cycling-coach-v4`
3. Para traer **todas** tus grabaciones de v2 sin sobrescribir las incluidas: `./scripts/import-v2-recordings.sh`. Puedes indicar otra ruta v2 como primer argumento.
4. Instala el adaptador: `python3 -m venv trainer-adapter/.venv && trainer-adapter/.venv/bin/python -m pip install -r trainer-adapter/requirements.txt`
5. Ejecuta `./start.sh` (requiere Java 21, Maven, Node y npm).
6. Abre `http://127.0.0.1:5173`. Por defecto usa el CSV real de 10 minutos incluido en `trainer-adapter/recordings`.

## Modo grabación física

En `.env` cambia `TRAINER_MODE=WAHOO`, `RECORD_ENABLED=true`, `HR_ENABLED=true`. **Deja `CONTROL_TEST_ENABLED=false`** salvo que quieras ejecutar expresamente un nuevo experimento físico controlado. `ZWIFT_ENABLED=true` conecta los mandos si configuras sus IDs; las marchas siguen siendo **solo visuales** y no envían cambios al rodillo.

## Qué está probado y qué falta

- Incluye la sesión CSV/JSONL de referencia que compartiste, más scripts de diagnóstico.
- La conexión BLE a Wahoo, HR50 y mandos fue confirmada anteriormente por ti con otras versiones.
- Esta reconstrucción v4 se valida aquí mediante las pruebas Python y comprobaciones de integridad; la prueba completa Java/React en tu Mac debe confirmarse allí.
- La pendiente mostrada es **pendiente ordenada** al rodillo, no medida físicamente; durante los primeros 5 minutos puede aparecer «—».
- Todavía **no** hay cambio de marchas físico desde Zwift Click.

## Seguridad de las grabaciones

No borres v2. El script importa solo archivos que no existan ya en v4, sin modificar origen. Haz copia externa de `trainer-adapter/recordings` antes de nuevas sesiones importantes. `.env` y datos privados quedan fuera de repositorios Git según `.gitignore`.
