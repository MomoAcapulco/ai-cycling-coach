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

## 1. Paso 5: rampa suave de pendiente (unos 3 min)

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

- [ ] Fichero `diagnostics/zwift_grade_test_*.json` generado
- [ ] Anotadas tus sensaciones: ¿notaste el 1 % y el 1,5 %? ¿algo brusco? ¿algo a los 60 s? ¿la marcha 13 a los 120 s?

**Aquí paramos.** Me pasas el fichero y ajusto la aplicación con lo que salga (unos minutos):
- si el 0 % exacto desactiva las marchas;
- si la pendiente se mantiene al cambiar de marcha;
- si el rodillo confirma la pendiente.

Este mismo fichero responde además a otra pregunta: si la velocidad del rodillo cambia con la pendiente a la misma
cadencia. Esperamos que no.

## 2. Aplicación: sesión con marchas y carretera virtual en llano (unos 10 min)

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

## 3. Paso 6: pendiente en la aplicación (unos 15 min)

Solo después de que haya ajustado la aplicación con el resultado del paso 1.

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

## 4. Opcional: calibrar el modelo de velocidad con Zwift (unos 10 min)

Sirve para afinar los coeficientes de la carretera virtual (CdA 0,40 y Crr 0,004).

En Zwift, sube un tramo de pendiente constante a potencia fija (por ejemplo 200 W) y anota la pendiente y la
velocidad que marca. Repite lo mismo en llano.

- [ ] Velocidades de Zwift anotadas (pendiente, vatios, km/h)

## Qué me pasas al final

- Todos los ficheros de `diagnostics/` nuevos.
- Los CSV o resúmenes de las sesiones (en `ai-cycling-coach-data/recordings/`), o dime su nombre.
- Tus notas de cada prueba.
