# Control del rodillo — Paso 2: abrir el canal Zwift del rodillo (sin marchas ni pendiente)

El paso 1 confirmó que tu KICKR CORE 2 (firmware 3.5.11) tiene el protocolo Zwift (servicio `FC82`).
Este paso abre ese canal como hacen Serpentine e Incyclist y **escucha** lo que responde el rodillo.

## Qué envía (y nada más)

Solo dos mensajes de arranque, al canal Zwift del rodillo:

1. `RideOn 02 01`
2. `41 08 05`

**No** envía marchas, **ni** pendiente, **ni** potencia objetivo, **ni** órdenes FTMS. El programa tiene un
bloqueo que rechaza cualquier otra escritura antes de que llegue al rodillo (probado con tests).

Es posible que el rodillo se ponga en su modo por defecto al recibir el arranque (como cuando abres Zwift):
por eso conviene **pedalear suave**. Si notas algo raro, deja de pedalear y pulsa **Ctrl+C**.

## Antes de empezar

- Cierra Zwift, Zwift Companion y la app de Wahoo.
- Si la aplicación está arrancada (`start.sh`), párala con Ctrl+C.
- Súbete a la bici o quédate al lado. Da unas pedaladas para despertar el rodillo.

## Comando

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/zwift_hub_probe.py --confirm --seconds 60
```

Durante los 60 segundos **pedalea suave y constante** (por ejemplo 70–80 rpm). Cada 5 s verás una línea como:

```
  t= 15.0s  zwift messages=42  riding data=40  last: 95 W 74 rpm
```

Al final, un resumen:

```
RidingData messages: ...  first after ... s
Zwift mean : {...}
FTMS  mean : {...}
Saved: .../diagnostics/zwift_hub_probe_AAAAMMDD_HHMMSS.json
```

## Qué tienes que pasarme

- El fichero `diagnostics/zwift_hub_probe_*.json` (se guarda dentro del proyecto, no hace falta copiarlo).
- Y dime si **notaste algún cambio de resistencia** al empezar o durante la prueba.

## Qué buscamos

- Que el rodillo responda con datos `RidingData` (potencia, cadencia, velocidad) tras el arranque.
- Que esos datos cuadren con los de FTMS.
- Qué otros mensajes envía (para el paso 3: marchas).
