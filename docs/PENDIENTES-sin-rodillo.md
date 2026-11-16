# Pendientes sin rodillo

Lo que se puede hacer y probar sin el rodillo, en orden. Lo que necesita el rodillo está en
`pruebas/PENDIENTES-con-el-rodillo.md`.

| # | Tarea | Estado |
|---|---|---|
| 1 | **Repositorio git**: público en github.com/MomoAcapulco/ai-cycling-coach, MIT, historial limpio | Hecho (13-11) |
| 2 | **Autodescubrimiento con varios dispositivos**: recordar todos los de cada tipo y no adivinar cuando hay varios desconocidos | Hecho (tests); falta probarlo con bandas reales (abajo) |
| 3 | **Rutas GPX**: subirlas, guardarlas, ver su perfil y elegir cuál rodar | Hecho (tests y simulador); falta probarlo tú con un GPX real (abajo) |
| 4 | **Exportar a FIT y validar las métricas** contra intervals.icu o GoldenCheetah (NP, TSS, desnivel) | FIT hecho y validado con las herramientas de Garmin; falta que compares en intervals.icu (`pruebas/VALIDAR-metricas-intervals.md`) |
| 5 | **Test de FTP** (rampa o 20 min) como primer entrenamiento guiado | Hecho (15-11), probado en el simulador; el test de verdad, con el rodillo (prueba 6 de la otra lista) |
| 6 | **Entrenamientos estructurados**: bloques con objetivo de vatios, primero sin ERG | Hecho (16-11): 7 entrenamientos para maratón de BTT, probado en el simulador; falta con el rodillo (prueba 7 de la otra lista) |
| 6b | **Aviso de FTP**: estimarlo tras cada sesión con el modelo de potencia crítica y proponer subirlo o hacer el test, nunca cambiarlo solo (abajo) | Hecho (16-11): con tu historial, rodillo 152 W; sin potencia en la calle |
| 7 | **Forma, fatiga y frescura** (CTL, ATL y TSB) con el historial de sesiones | Hecho (15-11), validado con el «Esfuerzo relativo» de Strava; mejora si pones tu pulso en reposo y tu umbral en el perfil |
| 8 | **Método del desnivel acumulado de las rutas**: decidirlo con GPX reales frente al desnivel oficial | Hecho (15-11): media de 50 m, a menos del 1 % de Strava en tus 3 rutas (abajo) |
| 9 | **Rutas generadas**: crear rutas a partir de distancia, desnivel, número de subidas… (abajo) | Pendiente |
| 10 | **Lo que necesita la IA además de 4–7**: tu objetivo y calendario, tus salidas en la calle, cómo te sientes, historial consultable, reglas y privacidad (abajo) | **10a hecha (15-11)**: historial + importación de Strava (118 actividades). Faltan objetivo y calendario, sensaciones, reglas |
| 11 | **IA, fase 1: análisis después de cada sesión** | Tras la 4, la 5 y parte de la 10 |
| 12 | **IA, fase 2: planificación** (semana, ajustes según cómo vas, puesta a punto para la carrera) | Tras la 6, la 7 y la 10 |
| 13 | **Visual 1: mapa en movimiento** con tu posición en la ruta | Pendiente |
| 14 | **Visual 2: vídeo real sincronizado** con tu velocidad | Pendiente |
| 15 | **Visual 3: mundo 3D generado del GPX** | Opcional, proyecto grande (abajo) |

## 2. Autodescubrimiento con varios dispositivos

Problema actual: se recuerda **un** dispositivo por tipo (rodillo, pulsómetro, mando izquierdo y derecho). Si el
recordado no está, el escaneo coge **el primero que responde** y sustituye al anterior. Con dos bandas cerca, podría
grabar el pulso de otra persona sin avisar.

Lo que se va a hacer:
- **Recordar todos los dispositivos** de cada tipo, con su nombre y la última vez que se usaron.
- **Un solo escaneo** que reúne todos los candidatos presentes, y entonces:
  - un conocido presente → lo usa;
  - varios conocidos presentes → el último usado;
  - ninguno conocido y uno solo nuevo → lo usa y lo añade a la lista;
  - ninguno conocido y varios nuevos → **no adivina**: avisa en el Panel y en Ajustes para que elijas.
- **En Ajustes**, por cada tipo: la lista de dispositivos con «Usar este» y «Olvidar».
- **El ID fijado en `.env` sigue mandando.**

La prueba con dispositivos reales no necesita el rodillo: tu HR50 y, si la tienes, una segunda banda.

### Probarlo con dispositivos reales (sin rodillo)

Con la aplicación arrancada (`./start.sh`), en **Ajustes**: modo **Simulador** y **Pulsómetro** activado.

1. **Ajustes → Dispositivos**: deben aparecer tus dispositivos de siempre (KICKR, HR50 y los dos Click), con su
   fecha de último uso.
2. **Si tienes otra banda, de cualquier marca**:
   - Ponte solo la otra banda: debe conectarse y aparecer en la lista **junto** a la HR50.
   - Ponte la HR50 y pulsa «Usar este» en ella: el pulso debe cambiar a la HR50 en unos segundos, sin reiniciar.
3. **Si tienes dos bandas que la aplicación no conoce**: pulsa «Olvidar» en las dos y enciéndelas a la vez. El
   Panel debe decir «varias bandas cerca, elige cuál en Ajustes», y en Ajustes debes poder elegir la tuya.

## 3. Probar las rutas GPX (sin rodillo, en el simulador)

1. Consigue el GPX de una carrera o de un puerto, **con altitud**. Las webs de las carreras suelen tenerlo, o se
   puede exportar de Strava, Komoot o RideWithGPS.
2. `./start.sh` → **Ajustes → Modo: Simulador**.
3. **Rutas → Subir GPX**. Revisa distancia, desnivel y pendiente máxima: ¿cuadran con lo que publica la carrera?
   Pulsa **Ver perfil**.
4. **Rodar esta ruta** → en el **Panel**, **Iniciar sesión**. Mira el perfil con tu posición, cómo cambia la
   pendiente según avanzas y cómo baja la velocidad en las subidas.
5. Comprueba que los botones de pendiente están bloqueados mientras ruedas la ruta, y que **Salir de la ruta**
   no provoca saltos.

Cuéntame si el desnivel calculado se parece al oficial de la carrera: es la mejor forma de validar el suavizado.

## 6b. Aviso de FTP

El FTP fija todos los objetivos de los entrenamientos, así que no se cambia solo: la aplicación propone y tú decides.

1. **Estimarlo después de cada sesión** con el modelo de potencia crítica: tus mejores esfuerzos de 3 a 20 minutos
   de las últimas 6–8 semanas (como intervals.icu o WKO), mejor que solo «0,95 × mejor 20 min».
2. **Si la estimación supera tu FTP un 3 % o más**: aviso «Has rendido por encima de tu FTP: ¿subirlo a X W?»,
   con un botón.
3. **Nunca bajarlo automáticamente**: los entrenamientos por debajo del umbral (sweet spot, tempo) no dicen
   cuánto podrías dar, y el FTP bajaría aunque estuvieras más en forma. Si llevas 6–8 semanas sin esfuerzos
   máximos, o la estimación cae mucho, el aviso es «toca test de FTP».
4. **Test de FTP cada 6–8 semanas**, y al empezar o terminar un bloque o antes de afinar para una carrera (para las
   maratones: al empezar la preparación y unas 3–4 semanas antes).
5. **Rodillo y calle por separado**: en el rodillo el FTP suele salir un 5–10 % más bajo. Para los
   entrenamientos de rodillo, el medido en el rodillo; el historial de Strava mezcla las dos cosas.

## 8. Desnivel acumulado de las rutas: decidir el método con GPX reales

La pendiente ya usa el método de Serpentine. El **desnivel acumulado** sigue con nuestro método original a propósito,
porque ningún método fue mejor en todo. Medido con rutas sintéticas (desnivel real entre paréntesis):

| Ruta | Nuestro | Serpentine (umbral 1 m) | gpxpy (suavizado ligero) | GoldenCheetah (umbral 3 m) |
|---|---|---|---|---|
| Puerto limpio (60) | 58,7 | 58,1 | 59,4 | 57,6 |
| Puerto con ruido de GPS (60) | 63,1 | 59,6 | 67,2 | 61,2 |
| 10 repechos de 2 m (20) | 9,6 | 1,1 | 15,4 | 0,0 |
| 10 repechos de 2 m con ruido (20) | 13,7 | 5,2 | 24,0 | 27,8 |

El ruido y los repechos los he modelado yo; los GPX reales pueden ser distintos (muchas carreras publican GPX
corregidos con mapas de elevación, casi sin ruido). Para decidir:
1. Junta 3 o 4 GPX de carreras o puertos con su **desnivel oficial** (el que publica la carrera, o el de
   Strava/Komoot/RideWithGPS). Mejor si hay de todo: un puerto largo, una ruta rompepiernas y una grabada con GPS.
2. Déjalos en `diagnostics/` (no se suben al repositorio).
3. Comparo los cuatro métodos con ellos y elegimos el que más se acerque.

## 9. Rutas generadas

Crear una ruta sin GPX, a partir de lo que quieres entrenar. Se guarda y se rueda como cualquier ruta subida.

Configuración propuesta (todo opcional menos la distancia):

| Parámetro | Ejemplo | Para qué |
|---|---|---|
| Distancia | 40 km | — |
| Desnivel positivo | 800 m | El total que reparten las subidas |
| Número de subidas | 5 | Cuántas, separadas por llano o bajada |
| Tipo de subida | repechos (0,3–1 km) · medias (1–4 km) · puertos (5–15 km) · mezcla | Su longitud |
| Pendiente máxima | 10 % | Ninguna rampa la supera |
| Irregularidad | baja · media · alta | Constante o con rampas y descansillos dentro de cada subida |
| Final | en llano · en alto | Termina subiendo, como un final de etapa |
| Vuelta al inicio | sí · no | Circuito: baja lo que sube |
| Semilla | 1234 | La misma configuración da siempre la misma ruta (para repetirla) |

- **Presets:** «llano», «rompepiernas», «media montaña», «montaña» y «como mi carrera». El último saca la
  distancia, el desnivel y las subidas de un GPX tuyo y genera variaciones parecidas.
- Antes de guardar, se ve el perfil. Lo imposible se avisa (por ejemplo, 2 000 m de desnivel en 20 km con
  máximo 8 %).
- Más adelante la IA podrá proponerte rutas así, por ejemplo: «hoy: 5 subidas de 2 km al 6 %».

## 10. Lo que necesita la IA además de 4–7

1. **Tu objetivo y tu calendario**: carrera, fecha, tipo y perfil (su GPX), y los días y horas que puedes
   entrenar.
2. **Tus salidas en la calle**: importar FIT de Garmin o Strava, o leerlos de intervals.icu. Sin ellas, la fatiga
   y la forma salen mal.
3. **Cómo te sientes**: una pregunta corta al terminar cada sesión (esfuerzo del 1 al 10, sensaciones,
   molestias).
4. **Historial consultable**: una base de datos local (SQLite) con todas las sesiones, en vez de CSV sueltos.
5. **Reglas y privacidad**:
   - La IA propone y el código valida (límites según tu FTP, rampas máximas), y nunca controla el rodillo
     directamente.
   - Son datos de salud: si se usa un modelo en la nube, tú decides qué se envía.

## 13–15. Parte visual (propia, sin copiar el mundo, los avatares ni el estilo de Zwift)

- **13. Mapa en movimiento**: OpenStreetMap con tu posición avanzando por la ruta, junto al perfil. Poco
  trabajo.
- **14. Vídeo real sincronizado**: un vídeo de un recorrido que avanza a tu velocidad (más lento si vas más
  lento), con tus propios vídeos (GoPro con GPS) o vídeos con licencia libre. Encaja con las rutas GPX. Es la
  mejor relación entre esfuerzo y sensación de carretera.
- **15. Mundo 3D generado del GPX**: terreno a partir de mapas de elevación abiertos, la carretera y el paisaje
  generados. Proyecto grande; Serpentine (MIT) hace algo así y serviría de referencia.

### 8b. Resultados con tus GPX reales (15-11)

Tus tres GPX son actividades exportadas de Strava. Desnivel calculado con cada método:

| Ruta | km | Nuestro | Serpentine | gpxpy | GoldenCheetah | Sin suavizar |
|---|---|---|---|---|---|---|
| Cuna de la Legión | 56,1 | 1 429 | 1 367 | 1 594 | 1 365 | 1 602 |
| La Africana | 74,2 | 1 062 | 991 | 1 195 | 963 | 1 206 |
| Sherry Bike Maratón | 66,0 | 996 | 940 | 1 091 | 900 | 1 103 |

Las cifras oficiales publicadas no sirven bien de referencia. La Cuna de la Legión 2025 dio 1 392 m, pero no está
claro que sea el recorrido de BTT. La Sherry Bike 2026 no publica el desnivel de sus 66,6 km. De La Africana no hay
datos recientes.

**Decisión (15-11)**, con el desnivel que muestra Strava (Cuna 1 501, Africana 1 118, Sherry 1 038 m):

| Ventana de suavizado | Cuna | Africana | Sherry |
|---|---|---|---|
| Sin suavizar | +6,3 % | +7,1 % | +5,6 % |
| 30 m | +2,4 % | +3,0 % | +2,7 % |
| **50 m (elegida)** | **−0,2 %** | **+0,4 %** | **+0,8 %** |
| 100 m (la anterior) | −4,8 % | −5,0 % | −4,0 % |

Los métodos con umbral (Serpentine y GoldenCheetah) daban entre −9 y −14 %, y gpxpy entre +5 y +7 %. Strava es una
referencia, no la verdad absoluta, pero es la cifra con la que se compara todo el mundo. Si más adelante subes
GPX de otro tipo (de GPS sin barómetro, o de organizadores), conviene repetir la comparación.
