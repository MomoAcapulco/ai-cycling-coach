# AI Cycling Coach v4.1 — Dashboard, Replay y marchas virtuales (sin control físico)

Versión **completa**, no parche. No sobrescribir v4 ni v2.

## Instalación en Mac

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

## Novedades

- Endpoint Python `/replay/session`: 600 registros íntegros para los gráficos, sin depender de cuándo se abra React.
- Endpoint Python `POST /replay/control`: `play`, `pause`, `restart`, `seek` y `speed` (0.5, 1, 2, 4).
- Endpoint Python `POST /replay/gear`: cambios visuales +1/-1, únicamente en modo REPLAY.
- API Spring Boot reenvía los tres endpoints bajo `/api/trainer/replay/...`.
- React: perfil de pendiente ordenada con tramo desconocido, línea temporal, reproductor, gráficos de potencia/pulso/cadencia de sesión completa, potencia suavizada tres segundos, estadísticas y marchas virtuales.
- Control del Wahoo sin cambios desde v4. No se ha habilitado el cambio físico. No se repite automáticamente el experimento de pendientes mientras REPLAY esté activo.

## Verificación realizada

- 31 pruebas unitarias de Python: OK.
- Prueba HTTP real de `/health`, `/replay/session`, pausa, salto al segundo 420, lectura de pendiente (2 %) y cambio virtual al 13: OK.
- Parseo TypeScript/TSX con compilador TypeScript global: sin errores sintácticos.
- **Pendiente de probar en tu Mac:** `npm install` y `npm run build` para verificar dependencias y compilación completa; prueba end-to-end React + Java.

## Si algo falla

```bash
cd ~/dev/ai-cycling-coach-v4.1/frontend
npm install
npm run build
```

Comparte el error exacto antes de modificar archivos. Mantén las grabaciones y `.env` de versiones antiguas intactos.
