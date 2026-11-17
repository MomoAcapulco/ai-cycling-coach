# Probar el calendario de pruebas

Sin rodillo. Unos 5 minutos. Recompila al arrancar (hay cambios en la interfaz y en el API Java).

```bash
./start.sh
```

Y los tests del API Java (hay uno nuevo para el calendario), en otra terminal:

```bash
cd backend && mvn test
```

## 1. Añadir tus pruebas

**Calendario → Añadir una prueba**, para cada carrera que preparas:

- [ ] Elige su recorrido en «Recorrido (de tus rutas)»: se ponen el nombre, la distancia y el desnivel. Cámbialos por los
  oficiales si quieres.
- [ ] Pon la fecha, el tipo y la prioridad (A la principal de la temporada).
- [ ] Sale en «Próximas pruebas» con los días que faltan; la más cercana, destacada.
- [ ] «Cambiar» y «Quitar» funcionan.

## 2. Una prueba pasada

Si alguna de tus carreras ya pasó (por ejemplo La Africana o La desértica), añádela con su fecha de verdad:

- [ ] Sale arriba en «¿Cómo fue?», con la actividad de ese día de tu historial ya elegida y su tiempo.
- [ ] Guarda el resultado: pasa a «Pruebas pasadas» con «Terminada en …».

## 3. El mes

- [ ] Cada prueba aparece en su día, con el color de su prioridad; los días que entrenaste, con un punto por actividad.
- [ ] ‹ › cambian de mes y «Hoy» vuelve al actual.

## 4. Una prueba por etapas

- [ ] **Añadir una prueba → «Varias etapas»**: salen dos etapas; «+ Añadir etapa» pone la siguiente al día siguiente.
- [ ] En una etapa, **Subir GPX** con un fichero tuyo: se pone en esa etapa con su distancia y su desnivel, y aparece
  también en **Rutas**.
- [ ] La prueba sale con «del … al …», el número de etapas y la suma de km y desnivel; debajo, la lista de etapas.
- [ ] En el mes, cada etapa en su día como «E1 · nombre», «E2 · nombre»…
- [ ] Si pones una prueba por etapas ya pasada, «¿Cómo fue?» sale una vez por etapa; al guardar todas, la prueba
  pasa a «Pruebas pasadas» con el tiempo total.
