# Control del rodillo — Paso 1: inventario del rodillo (solo lectura)

Conecta con el KICKR, lista todo lo que ofrece por Bluetooth y lo guarda en un fichero.
**No envía nada al rodillo**: ni órdenes, ni pendiente, ni marchas. La resistencia no cambia.

Para qué sirve: saber si tu KICKR CORE 2 ofrece el **protocolo Zwift** (servicio `FC82` o `19ca`).
Si lo ofrece, las marchas virtuales las hará el propio rodillo (como con Zwift); si no, las imitaremos por FTMS.

## Antes de empezar

- Cierra Zwift, Zwift Companion y la app de Wahoo (el rodillo solo admite una app conectada).
- Si la aplicación está arrancada (`start.sh`), párala con Ctrl+C.
- Rodillo enchufado. Justo antes de lanzar el comando, **da unas pedaladas** para despertarlo.
- No hace falta estar pedaleando durante la prueba.

## Comandos

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/trainer_probe.py --seconds 15
```

(Si es la primera vez en esta carpeta, antes: `bash init.sh`.)

## Qué verás

Algo parecido a:

```
Connecting (read-only) to KICKR CORE 0000 <identificador> ...
Trainer: KICKR CORE 0000  model=...  firmware=...
  service 00001826-...  Fitness Machine (FTMS)  (n characteristics)
  service 0000fc82-...  Zwift (FC82)  (n characteristics)
  ...
Zwift service exposed: YES
Saved: diagnostics/trainer_probe_AAAAMMDD_HHMMSS.json
```

La línea importante es **`Zwift service exposed: YES / NO`**.

Si dice `No trainer found`: pedalea un poco y repite, o prueba con `--seconds 30`.

## Qué tienes que pasarme

- El fichero `diagnostics/trainer_probe_*.json` (la última línea dice dónde está).
- Si puedes, también un escaneo general con el rodillo encendido (paso 2 del autodescubrimiento):

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/discovery.py --seconds 15
```

## Siguientes pasos (no ahora)

2. Arranque del protocolo nativo **sin cambiar marchas**: comprobar que el rodillo responde con datos.
3. Pocas marchas con poco esfuerzo, supervisado y con parada inmediata.

Cada uno irá detrás de su propio interruptor en `.env`, desactivado por defecto.
