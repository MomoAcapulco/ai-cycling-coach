# Control del rodillo — Paso 3: unas pocas marchas virtuales (supervisado)

**Este paso SÍ cambia la resistencia del rodillo**, de forma suave: solo las marchas 11, 12 y 13, alrededor de la
neutra de Zwift (12). Dura unos 100 segundos.

## Qué hace, segundo a segundo

| Tiempo | Qué pasa | Qué deberías notar |
|---|---|---|
| 0 – 10 s | Nada. Mide tu pedaleo en el modo libre de siempre | Lo normal |
| 10 s | Abre el modo Zwift del rodillo y pone la **marcha 12** con tus pesos y 0,4 % de pendiente | Puede subir un poco la resistencia (lo que notaste en el paso 2) |
| 30 s | **Marcha 13** (un poco más dura) | Algo más de resistencia |
| 45 s | Marcha 12 | Vuelve a lo de antes |
| 60 s | **Marcha 11** (un poco más fácil) | Algo menos de resistencia |
| 75 s | Marcha 12 | Vuelve a lo de antes |
| 90 s | Fin: deja la marcha 12 y 0,4 % | — |

## Seguridad

- Un bloqueo solo deja enviar **exactamente** esos mensajes. Cualquier otra cosa (marchas más duras, pendiente,
  potencia, FTMS, actualización de firmware) se rechaza antes de llegar al rodillo.
- Si dejas de pedalear (menos de 40 rpm), **no** pasa a la marcha 13.
- Si se pierden los datos del rodillo más de 3 s, la prueba **para y vuelve a la marcha 12**.
- **Ctrl+C** en cualquier momento: para y vuelve a la marcha 12.
- Si algo te parece raro: **deja de pedalear** y pulsa Ctrl+C.

## Antes de empezar

- Cierra Zwift, Zwift Companion y la app de Wahoo. Si la aplicación está arrancada, párala con Ctrl+C.
- Súbete a la bici. Da unas pedaladas para despertar el rodillo.
- **Pedalea suave y lo más constante posible durante toda la prueba** (por ejemplo 70 rpm). Así se ve bien el
  efecto de cada marcha en la potencia.

## Comando

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/zwift_gear_test.py --confirm
```

Los pesos se toman de tu perfil guardado (Ajustes → Perfil). Si aún no lo has guardado, añade
`--rider-kg <tu peso> --bike-kg <peso de la bici>`.

Verás una línea por cada paso, por ejemplo:

```
  t= 10.0s  ride_on   now 95 W 70 rpm
  t= 10.9s  gear_12   now 98 W 70 rpm
  t= 30.9s  gear_13   now 101 W 70 rpm
```

y al final una tabla por tramo (potencia, cadencia, velocidad) y dónde se guardó el fichero.

## Qué tienes que pasarme

- El fichero `diagnostics/zwift_gear_test_*.json` (se guarda dentro del proyecto).
- **Tus sensaciones**: ¿notaste el cambio en cada marcha? ¿alguno brusco? ¿el arranque del modo Zwift?
