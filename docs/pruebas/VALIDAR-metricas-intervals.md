# Validar nuestras métricas con intervals.icu (sin rodillo)

intervals.icu lee el FIT y **recalcula** la potencia normalizada, el trabajo y el resto a su manera. Si sus
números coinciden con los nuestros, nuestras métricas son fiables. GoldenCheetah sirve igual, si lo prefieres.

> Subir el FIT a intervals.icu es enviar tus datos a un servicio externo: potencia, pulso, cadencia y fecha. No
> lleva GPS. Hazlo solo si te parece bien.

## 1. Elige una sesión y descarga su FIT

Mejor una de **20 minutos o más**: la potencia normalizada tiene poco sentido en sesiones muy cortas. Si todavía
no tienes ninguna así, haz una en el simulador o con el rodillo.

**Sesiones** → en la sesión elegida, **Descargar FIT**.

## 2. Súbela a intervals.icu

En intervals.icu (la cuenta gratuita sirve): **Activities → Upload**, o arrastra el fichero `.fit`.

Si ya tienes FTP en el perfil de la aplicación, pon el **mismo FTP** en intervals.icu (Settings → Cycling → FTP),
para comparar también IF y TSS.

## 3. Compara

Apunta los valores de las dos y pásamelos (o mándame una captura de cada una):

| Métrica | Nuestra (página Sesiones) | intervals.icu | Diferencia esperada |
|---|---|---|---|
| Tiempo (sin pausas) | | Moving / Elapsed time | igual |
| Distancia | | Distance | igual (la del FIT) |
| Potencia media | | Avg Power | ±1 W |
| Potencia normalizada (NP) | | Norm Power / NP | ±2 W |
| Potencia máxima | | Max Power | igual |
| Trabajo | | Work (kJ) | ±1 % |
| Cadencia media | | Avg Cadence | ±1 rpm (puede contar o no los ceros) |
| Pulso medio / máximo | | Avg / Max HR | ±1 |
| Desnivel | | Elevation gain | puede variar: cada uno suaviza la altitud a su manera |
| IF y TSS (si hay FTP) | | Intensity / Load | ±2 % |

Las diferencias pequeñas son normales (redondeos, y si los segundos sin pedalear cuentan como 0 W o no). Si alguna
pasa claramente de lo esperado, la investigo.
