# Paso 2 — Escaneo Bluetooth (solo lectura)

Lista el rodillo, el pulsómetro y los mandos Zwift que hay alrededor y guarda sus anuncios Bluetooth en un fichero. No se conecta ni envía nada a ningún dispositivo.

## Antes de empezar

- Cierra Zwift, Zwift Companion y la app de Wahoo (si están conectados a los dispositivos, no se anuncian).
- Rodillo encendido: da unas pedaladas para despertarlo.
- Pulsómetro puesto (o humedece los electrodos) para que emita.
- Mandos Zwift despiertos: pulsa un botón de cada uno.
- Si la app está arrancada (`start.sh`), páralo con Ctrl+C.

## Comandos

Abre Terminal y ejecuta, uno a uno:

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

Solo si es la primera vez en esta carpeta (crea el entorno de Python):

```sh
bash init.sh
```

El escaneo (15 segundos):

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/discovery.py --seconds 15
```

**Mientras dura el escaneo, pulsa varias veces un botón de cada mando** (por ejemplo `+` en el derecho y `−` en el izquierdo).

Si macOS pide permiso de Bluetooth para Terminal, acéptalo y repite el escaneo.

## Qué verás

Una línea por dispositivo, por ejemplo:

```
trainer    KICKR CORE 0000   <identificador>  rssi=-55  (service 00001826)
zwift      Zwift Play        <identificador>  rssi=-60 side=left  (zwift type 0x03)
heart_rate HR50 ...          <identificador>  rssi=-70  (service 180d)
```

y al final la ruta del fichero guardado:

```
Raw advertisements saved: diagnostics/ble_scan_AAAAMMDD_HHMMSS.json
```

## Qué tienes que pasarme

El fichero `diagnostics/ble_scan_*.json` que indica la última línea (y, si puedes, la salida de la pantalla).

Con él sabremos el byte de tipo de tus mandos (izquierdo/derecho o "firmware 2") y si el KICKR anuncia también el servicio Zwift.

## Opciones (no hacen falta ahora)

- `--all`: muestra también los dispositivos desconocidos.
- `--remember`: además guarda lo que no sea ambiguo en `~/dev/ai-cycling-coach-data/devices.json`.
- `--seconds 30`: escaneo más largo si algo no aparece.
