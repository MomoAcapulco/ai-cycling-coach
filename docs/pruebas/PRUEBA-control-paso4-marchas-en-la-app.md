# Control del rodillo — Paso 4: marchas con los mandos, desde la aplicación

Ahora las marchas virtuales **mueven el rodillo** desde la aplicación normal, con tus mandos Zwift Click o con los
botones del panel. Es lo mismo que el paso 3, pero permanente y con todas las marchas (1–24, como Zwift).

## Qué hace

- Empieza en la **marcha 12**. «+» del mando derecho endurece; «−» del izquierdo suaviza.
- Pulsaciones rápidas seguidas se juntan en un solo cambio (por ejemplo, tres «+» seguidos = un salto de 12 a 15).
- El número grande del panel es la marcha **que ha confirmado el rodillo**. Mientras espera la confirmación verás
  «Pedida: …».
- **Sin pedalear (menos de 40 rpm) o sin datos del rodillo, no endurece** (suavizar sí).
- Si el rodillo no confirma un cambio, se reintenta 3 veces y, si no, se queda en la última marcha confirmada y lo indica.
- Al parar la aplicación (Ctrl+C en la terminal de `start.sh`) el rodillo vuelve a la **marcha 12**.
- La pendiente **no cambia** (0,4 % fijo, el mínimo que necesita el rodillo para aceptar marchas).

## Preparación (una vez)

1. Cierra Zwift, Zwift Companion y la app de Wahoo.
2. Arranca la aplicación:

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
./start.sh
```

3. Abre `http://127.0.0.1:5173/#/ajustes`:
   - **Perfil del ciclista**: comprueba tu peso y el de la bici y pulsa «Guardar perfil» si no estaba guardado.
   - **Fuente de datos**: «Rodillo real».
   - **Sensores**: activa «Mandos Zwift» (y el pulsómetro si quieres).
   - **Control de marchas del rodillo**: actívalo.
   - Pulsa **Aplicar**.

## Prueba

1. Vuelve al **Panel**. Pedalea suave. En «Marchas virtuales» debe poner **CONTROLAN EL RODILLO** y la marcha **12**
   con «Marcha confirmada por el rodillo».
2. Pulsa «+» una vez: debe pasar a 13 y notarlo. Luego «−» para volver a 12.
3. Prueba varias pulsaciones seguidas («+ + +»): un solo salto a 15. Vuelve a 12 con «− − −».
4. Deja de pedalear y pulsa «+»: **no debe endurecer** (aparece el aviso). «−» sí funciona.
5. Prueba los botones «− Más fácil» / «+ Más duro» del panel: hacen lo mismo que los mandos.
6. Para la aplicación con Ctrl+C en la terminal: el rodillo debe volver a la marcha 12.

Si algo no va como esperas: deja de pedalear y para la aplicación con Ctrl+C.

## Qué tienes que contarme

- Si cada cambio se nota y si alguno es brusco.
- Si la marcha del panel coincide con lo que sientes y si aparece algún «UNCONFIRMED».
- Pulsa **«Iniciar sesión»** en el Panel antes de probar y **«Terminar»** al acabar: la sesión (CSV con la marcha de
  cada segundo y resumen) queda en `~/dev/ai-cycling-coach-data/recordings/` y en la página **Sesiones**, donde
  puedo verla directamente.
