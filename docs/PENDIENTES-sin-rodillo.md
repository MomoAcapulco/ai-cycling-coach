# Pendientes sin rodillo

Lo que se puede hacer y probar sin el rodillo, en orden. Lo que necesita el rodillo está en
`pruebas/PENDIENTES-con-el-rodillo.md`.

| # | Tarea | Estado |
|---|---|---|
| 1 | **Repositorio git**: público en github.com/MomoAcapulco/ai-cycling-coach, MIT, historial limpio | Hecho (13-11) |
| 2 | **Autodescubrimiento con varios dispositivos**: recordar todos los de cada tipo y no adivinar cuando hay varios desconocidos | Hecho (tests); falta probarlo con bandas reales (abajo) |
| 3 | **Rutas GPX**: subirlas, guardarlas, ver su perfil y elegir cuál rodar | Hecho (tests y simulador); falta probarlo tú con un GPX real (abajo) |
| 4 | **Exportar a FIT y validar las métricas** contra intervals.icu o GoldenCheetah (NP, TSS, desnivel) | Pendiente |
| 5 | **Test de FTP** (rampa o 20 min) como primer entrenamiento guiado | Pendiente |
| 6 | **Entrenamientos estructurados**: bloques con objetivo de vatios, primero sin ERG | Pendiente |
| 7 | **Forma, fatiga y frescura** (CTL, ATL y TSB) con el historial de sesiones | Pendiente |
| 8 | **Método del desnivel acumulado de las rutas**: decidirlo con GPX reales frente al desnivel oficial | Pendiente: necesita tus GPX (abajo) |

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
