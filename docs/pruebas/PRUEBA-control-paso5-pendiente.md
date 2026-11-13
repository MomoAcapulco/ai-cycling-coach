# Control del rodillo — Paso 5: una rampa suave de pendiente (supervisado)

**Este paso SÍ cambia la resistencia del rodillo**, de forma suave: pendientes de 0,4 %, 1 % y 1,5 %, con la marcha
fija en la 12. Dura unos 2 minutos y medio.

Sirve para responder a tres preguntas antes de usar la pendiente en la aplicación:
1. ¿El rodillo aplica la pendiente que le mandamos? (se ve en la potencia a la misma cadencia)
2. ¿Si después mandamos solo una marcha, se mantiene la pendiente? (la aplicación manda las marchas por separado)
3. ¿Con 0 % exacto el rodillo sigue haciendo caso a las marchas? (Incyclist manda 0,01 % por si acaso)

Y además mira si el rodillo **confirma** la pendiente de alguna forma (como confirma las marchas).

## Qué hace, segundo a segundo

| Tiempo | Qué pasa | Qué deberías notar |
|---|---|---|
| 0 – 10 s | Nada. Mide tu pedaleo en el modo libre de siempre | Lo normal |
| 10 s | Abre el modo Zwift y pone **0,4 % y marcha 12** con tus pesos | Lo mismo que al empezar el paso 3 |
| 30 s | **1 %** | Algo más de resistencia |
| 50 s | **1,5 %** | Un poco más todavía |
| 60 s | Vuelve a mandar la marcha 12 (sin tocar la pendiente) | **Nada**, si el rodillo mantiene el 1,5 % |
| 70 s | 1 % | Algo menos |
| 90 s | 0,4 % | Como al principio |
| 110 s | **0 %** exacto | Casi igual que 0,4 % |
| 120 s | Marcha 13 (con 0 %) | Un poco más duro… si las marchas siguen funcionando con 0 % |
| 130 s | Marcha 12 | Vuelve |
| 140 s | 0,4 % | — |
| 155 s | Fin: deja 0,4 % y marcha 12 | — |

Para que sepas qué esperar: cada 1 % de pendiente añade, a 65 rpm en la marcha 12 (unos 20 km/h virtuales),
**unos 0,55 W por cada kilo** de peso total, ciclista más bici: con 70 kg, unos 40 W; con 95 kg, unos 50 W. Cada
escalón de esta prueba (0,5–0,6 %) añade más o menos la mitad de eso. **Nunca pasa del 1,5 %.**
Por eso conviene pedalear a **60–70 rpm**: a más cadencia, más velocidad virtual y más vatios por cada 1 %.

## Seguridad

- Un bloqueo solo deja enviar **exactamente** los mensajes de esta tabla. Cualquier otra cosa (más del 1,5 %,
  pendientes negativas, potencia/ERG, otras marchas, viento, FTMS, actualización de firmware) se rechaza antes de
  llegar al rodillo.
- Si pedaleas a menos de 40 rpm, **se salta** cualquier paso que endurezca (subir la pendiente o la marcha 13). Los
  que suavizan sí se hacen.
- Antes de **cada** envío comprueba que llegan datos del rodillo; si se pierden más de 3 s, la prueba **para y
  vuelve a 0,4 % y marcha 12**. Sin datos del rodillo no envía nada.
- **Ctrl+C** en cualquier momento: para y vuelve a 0,4 % y marcha 12.
- Si algo te parece raro: **deja de pedalear** y pulsa Ctrl+C.

## Antes de empezar

- Cierra Zwift, Zwift Companion y la app de Wahoo. Si la aplicación está arrancada, párala con Ctrl+C.
- Súbete a la bici. Da unas pedaladas para despertar el rodillo.
- **Pedalea suave y lo más constante posible toda la prueba** (60–70 rpm). Si la cadencia cambia, la
  potencia cambia por eso y no se ve el efecto de la pendiente.

## Comando

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/zwift_grade_test.py --confirm
```

Los pesos se toman de tu perfil guardado (Ajustes → Perfil). Si aún no lo has guardado, añade
`--rider-kg <tu peso> --bike-kg <peso de la bici>`.

Verás una línea por cada paso, por ejemplo:

```
  t= 10.0s  ride_on           now 85 W 65 rpm
  t= 10.9s  start_0.4_gear_12  now 88 W 65 rpm
  t= 30.9s  grade_1.0         now 130 W 65 rpm
```

y al final una tabla por tramo (potencia media, potencia de los últimos 5 s, cadencia, velocidad y qué respuestas
mandó el rodillo), si la marcha se confirmó con 0 %, y dónde se guardó el fichero.

## Qué tienes que pasarme

- El fichero `diagnostics/zwift_grade_test_*.json` (se guarda dentro del proyecto).
- **Tus sensaciones**: ¿notaste el 1 % y el 1,5 %? ¿Algún cambio brusco? ¿Notaste algo a los 60 s (al reenviar la
  marcha)? ¿Y la marcha 13 a los 120 s?

## Después

Con los resultados ajusto la pendiente en la aplicación (ya está hecha y probada en simulación, pero **márcala como
no probada con el rodillo** hasta este paso):
- si el 0 % exacto apaga las marchas, se queda el 0,01 % que se manda ahora en su lugar;
- si al mandar una marcha se pierde la pendiente, la aplicación volverá a mandar la pendiente tras cada marcha;
- si el rodillo confirma la pendiente, el panel pasará a mostrar «aplicada» en vez de «enviada».
