# AI Cycling Coach v4.2 — Visualización progresiva y perfil suavizado

Versión **completa**, autocontenida. Instala en carpeta nueva `~/dev/ai-cycling-coach-v4.2`, **sin fusionar** con v4.1. Los archivos reales de 10 minutos están incluidos en `trainer-adapter/recordings/` y se conservan los originales.

## Novedades

- REPLAY: las curvas de potencia, frecuencia cardíaca y cadencia **crecen con el tiempo reproducido**. Alterna **Durante la sesión** / **Análisis completo** para consultar la sesión entera sin esperar.
- Pendiente: silueta suavizada **solo estética**, más línea discontinua escalonada con la **orden FTMS original**. La tarjeta muestra el valor original exacto; los primeros cinco minutos se mantienen como *sin orden registrada*, no 0 %.
- Cursor de reproducción sobre todas las gráficas. Potencia instantánea y media móvil de 3 segundos siguen visibles.
- Botones de reproducción y marcha virtual como en v4.1. **Incorporada la corrección del controlador Java para POST de JSON con longitud conocida**. Si hay errores upstream, el backend devuelve datos diagnósticos.
- **Ningún control físico de marchas:** las 24 relaciones son ilustrativas. Modo REPLAY no envía instrucciones al KICKR. El perfil no es una elevación GPX medida.

## Instalación en Mac

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

## Comprobaciones locales realizadas

- Python: **31 pruebas unitarias superadas**.
- TypeScript TSX: **análisis sintáctico sin errores** por TypeScript global.
- Scripts bash: análisis sintáctico correcto.
- **No se ha podido ejecutar `npm install` ni compilar React contra sus dependencias** en este entorno porque no están en caché y no hay acceso al registro de npm. Se realizará en tu Mac con `init.sh`.
- **No se ha recompilado Java en este entorno** (Maven no está disponible aquí); `init.sh` recompila el backend en tu Mac.
