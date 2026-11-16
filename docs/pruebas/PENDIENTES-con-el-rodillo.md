# Pruebas pendientes con el rodillo

Lista única de todo lo que hay que probar con el rodillo delante, en el orden en que conviene hacerlo. Cada prueba
nueva que necesite el rodillo se añade aquí. Al terminar cada una, márcala con una X y deja el fichero que genere en
`diagnostics/`.

**Tiempo total:** unos 45 minutos, más las pausas para revisar resultados.

## 0. Antes de subirte a la bici (en el Mac)

Comprueba que todo compila en tu máquina; en el contenedor solo se pudo compilar con un apaño.

```sh
cd ~/dev/ai-cycling-coach-v4.3.0/backend && mvn test
```

```sh
cd ~/dev/ai-cycling-coach-v4.3.0/frontend && npm run build
```

- [ ] `mvn test` en verde
- [ ] `npm run build` sin errores

Cierra Zwift, Zwift Companion y la app de Wahoo.

## 1. Paso 5: rampa suave de pendiente (unos 3 min) — ✅ HECHO el 13-11

Resultado: el rodillo confirma la pendiente (respuesta 512), el 0 % exacto funciona y la aplicación ya está
ajustada. Puedes hacer la prueba 3.

Usa la herramienta, no la aplicación: con la aplicación arrancada no funciona.

Guía completa: `PRUEBA-control-paso5-pendiente.md`. Pedalea a 60–70 rpm durante toda la prueba.

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
trainer-adapter/.venv/bin/python trainer-adapter/tools/zwift_grade_test.py --confirm
```

Los pesos se toman de tu perfil guardado (Ajustes → Perfil). Si aún no lo has guardado, añade
`--rider-kg <tu peso> --bike-kg <peso de la bici>`.

- [x] Fichero `diagnostics/zwift_grade_test_*.json` generado
- [x] Anotadas tus sensaciones ("muy naturales y nada exagerados"): ¿notaste el 1 % y el 1,5 %? ¿algo brusco? ¿algo a los 60 s? ¿la marcha 13 a los 120 s?

**Aquí paramos.** Me pasas el fichero y ajusto la aplicación con lo que salga (unos minutos):
- si el 0 % exacto desactiva las marchas;
- si la pendiente se mantiene al cambiar de marcha;
- si el rodillo confirma la pendiente.

Este mismo fichero responde además a otra pregunta: si la velocidad del rodillo cambia con la pendiente a la misma
cadencia. Esperamos que no.

## 2. Aplicación: sesión con marchas y carretera virtual en llano (unos 10 min) — ✅ HECHA el 13-11

Todo bien salvo tres cosas, ya corregidas y por comprobar en la prueba 5: el reloj de sesión, que las gráficas
no empezaban de cero y que el pulsómetro no conectó.

Esta prueba no depende del paso 5.

```sh
cd ~/dev/ai-cycling-coach-v4.3.0 && ./start.sh
```

En **Ajustes**: modo **Rodillo real**, **control de marchas** activado, mandos y pulsómetro activados, y tu perfil
guardado (tu peso y el de la bici).

1. **Iniciar sesión** en el Panel y pedalear 5 minutos cambiando de marcha con los mandos.
2. Fíjate en:
   - la **velocidad**: la de la carretera, comparada con la del rodillo que sale debajo;
   - la **distancia**;
   - el **W/kg**.
3. Pulsa **Pausa**, sigue pedaleando 30 s y luego **Continuar**: la distancia no debe sumar lo que pedaleaste en
   pausa.
4. **Terminar**. En **Sesiones**, revisa el resumen y descarga el CSV.

- [ ] La sesión aparece en Sesiones con distancia, W/kg y mejores esfuerzos
- [ ] La pausa no sumó distancia
- [ ] Al salir con Ctrl+C, el rodillo vuelve a la marcha 12
- [ ] Anotado si la velocidad de la carretera te pareció creíble

## 3. Paso 6: pendiente en la aplicación (unos 15 min) — ✅ HECHA el 13-11

«Todo bien con la pendiente». Los botones ±0,5 % solo contaban una pulsación por segundo: ya corregido, por
comprobar en la prueba 5. Falta probar una ruta GPX con el rodillo (abajo, en la 5).

Ya ajustada con el resultado del paso 1: puedes hacerla. Ahora el panel muestra «Aplicada ✓» cuando el rodillo confirma la pendiente.

Mismos ajustes que en la prueba 2. Inicia una sesión y prueba, de menos a más:

1. **+0,5 %** varias veces hasta el 2 %. Tiene que ir subiendo poco a poco, según avanzas.
2. **Deja de pedalear** con una pendiente pedida más alta: no debe endurecer hasta que vuelvas a pedalear.
3. Sube hasta el **5–6 %** con el deslizador. Con dificultad al 50 %, el rodillo aplica la mitad. Baja de marcha
   para mantener la cadencia.
4. Haz una **bajada**, por ejemplo −3 %: se suaviza, la velocidad sube y el desnivel no suma.
5. Vuelve a **llano 0 %**.
6. **Terminar** la sesión y revisar el perfil del recorrido, el desnivel y el VAM en Sesiones.
7. Sal con **Ctrl+C**: el rodillo debe quedar en 0,4 % y marcha 12.

- [ ] Las transiciones se sienten progresivas, sin muros
- [ ] Parado no endurece
- [ ] El panel muestra la pendiente de la carretera, la del rodillo y la enviada
- [ ] El desnivel de la sesión cuadra con el perfil
- [ ] Anotado si 20 m por cada 1 % te parece realista, o cuánto pondrías
- La ruta GPX con el rodillo pasó a la prueba 5.

## 4. Opcional: calibrar el modelo de velocidad con Zwift (unos 10 min) — ya no hace falta

Los datos del paso 5 ya lo han validado: a igual potencia y pendiente, nuestra velocidad se queda a ±1 km/h de la
del propio rodillo.

Sirve para afinar los coeficientes de la carretera virtual (CdA 0,40 y Crr 0,004).

En Zwift, sube un tramo de pendiente constante a potencia fija (por ejemplo 200 W) y anota la pendiente y la
velocidad que marca. Repite lo mismo en llano.

- [ ] Velocidades de Zwift anotadas (pendiente, vatios, km/h)

## 5. Re-comprobar lo corregido el 13-11 (unos 10 min)

Reinicia `./start.sh` para cargar los cambios.

- [ ] **Reloj de sesión**: marca `--:--` hasta «Iniciar sesión», sigue corriendo si dejas de pedalear y se para
  con «Pausar»
- [ ] **Sesión nueva**: al «Terminar» e «Iniciar» otra, las gráficas, el perfil y la pendiente máxima empiezan de cero
- [ ] **Botones ±0,5 %**: cinco pulsaciones seguidas suben la pendiente pedida 2,5 % de golpe
- [ ] **Pulsómetro**: con la banda puesta, humedecida y sin conectar a otro aparato, conecta. Si no, apunta el
  motivo que muestra el Panel
- [ ] **Una ruta GPX corta** con el rodillo (Rutas → «Rodar esta ruta»): las subidas se notan progresivas y
  «Salir de la ruta» no da tirones
- [ ] (Tuyo) **Marcha 24 en Zwift**: ¿se parece a lo que notas aquí?
- [ ] **Modo BTT** (Ajustes → Perfil → Tipo de bici: BTT, guardar y reiniciar `./start.sh`). En la marcha 12 y en
  llano, el rodillo debe notarse más duro que en carretera (más rodadura): unos 25-40 W más a 18 km/h según el
  peso. ¿Te parece realista para tierra? La velocidad «en la carretera virtual» debe ser menor que en carretera.

## 6. Test de FTP (unos 20–25 min, esfuerzo máximo)

Hazlo **descansado**, en un día sin entrenamiento fuerte la víspera. Si notas mareo, dolor en el pecho o algo raro,
deja de pedalear: el test termina solo.

1. `./start.sh` → modo **Rodillo real** con control de marchas. Pon el **pulsómetro**: el test anota tu pulso
   máximo.
2. En el **Panel → Test de FTP → Empezar test de FTP**. Se inicia la sesión sola.
3. **5 minutos suaves.** Después el objetivo sube 20 W cada minuto: **súbelo con las marchas**, a una cadencia
   cómoda (80–90 rpm). El panel te dice si vas por debajo o por encima.
4. Aguanta **hasta que no puedas mantener el objetivo**. Entonces deja de pedalear: termina solo.
5. Pulsa **Guardar como mi FTP**, rueda suave unos minutos y **Termina** la sesión.

- [ ] FTP estimado y guardado: ____ W (y el pulso máximo: ____ ppm)
- [ ] ¿Ha sido fácil seguir el objetivo con las marchas, o los saltos de 20 W eran incómodos con las marchas
  que tienes?

## 7. Entrenamiento estructurado (unos 40–65 min; otro día, no el del test)

Mejor **después del test de FTP**, para que los objetivos usen tu FTP real (si no, usa el estimado con tu historial).

1. `./start.sh` → modo **Rodillo real** con control de marchas.
2. **Entrenamientos** → elige uno. Para empezar, **Recuperación activa** (40 min, suave) o **Sweet spot 3×12**
   (66 min) → **Empezar**. Se inicia la sesión sola y vas al Panel.
3. Sigue el **objetivo** de cada bloque con las marchas y la cadencia que indica. Prueba una vez **Pausar** y
   **Continuar** la sesión: el entrenamiento debe pararse y seguir donde estaba.
4. Al acabar sale la tabla de cada bloque. **Cerrar** y **Terminar** la sesión. En **Sesiones** debe aparecer
   con el nombre del entrenamiento y su cumplimiento.

- [ ] Entrenamiento: ____________ · cumplimiento ____ % · en rango ____ %
- [ ] ¿Se ve bien el objetivo desde la bici (tamaño, colores)? ¿Echas algo en falta mientras pedaleas?
- [ ] ¿Los saltos de marcha permiten acercarse al objetivo (±10 %), o hay bloques imposibles de clavar?

## Qué me pasas al final

- Todos los ficheros de `diagnostics/` nuevos.
- Los CSV o resúmenes de las sesiones (en `ai-cycling-coach-data/recordings/`), o dime su nombre.
- Tus notas de cada prueba.
