# Importar tu historial (Strava)

El historial junta tus sesiones en el rodillo (entran solas) con lo que haces fuera: bici en la calle, carrera,
fuerza… Se guarda en tu carpeta de datos (`ai-cycling-coach-data/coach.db` y `history/files`; hasta el 16-11 era `history.db`), nunca en el
repositorio. Lo verás en la página **Historial**.

## 1. Pide tu exportación a Strava

strava.com → foto de perfil → **Ajustes → Mi cuenta → Descarga o elimina tu cuenta → Solicitar archivo**. Llega
un correo con un enlace a un ZIP (`export_12345678.zip`).

## 2. Impórtala

Con el ZIP descargado (por ejemplo en `Descargas`):

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/import_strava.py ~/Downloads/export_12345678.zip
```

Al terminar dice cuántas actividades ha añadido. Si vuelves a importar una exportación más nueva, **solo añade lo
nuevo**: no duplica nada.

## 3. Después

- **Borra el ZIP o guárdalo fuera del proyecto**: tiene todos tus datos de Strava y ya no hace falta. (Si lo dejas
  en la carpeta del proyecto, git lo ignora, pero ocupa sitio.)
- En **Historial** verás las horas por semana y todas las actividades.

## Qué se lee

- De cada actividad con fichero FIT (la mayoría): potencia, pulso, cadencia, distancia, tiempo en movimiento.
  La NP (potencia normalizada) se calcula con el método de Coggan, el mismo de las sesiones.
- El **desnivel** es el que muestra Strava, para que coincida con lo que ves allí.
- De las actividades sin FIT (GPX antiguos, entrenamientos manuales): las cifras de Strava.

Sobre la NP: la «potencia ponderada» de Strava sale de media un 2 % más baja que nuestra NP (unos 4 W en tus
salidas de Zwift). Strava usa un cálculo propio que no publica; el nuestro es el de Coggan, el mismo que
intervals.icu, TrainingPeaks y GoldenCheetah.
