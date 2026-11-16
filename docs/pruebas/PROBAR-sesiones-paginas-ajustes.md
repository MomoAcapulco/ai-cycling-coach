# Probar: sesiones en la base de datos, listas por páginas y Ajustes en pestañas

Sin rodillo. Unos 10 minutos.

## 0. Antes de arrancar: dos ficheros viejos en tu carpeta de datos

En `~/dev/ai-cycling-coach-data/` hay un `profile.json` y un `settings.json` **del 12-11**: los volvió a copiar
un fallo (ya corregido) desde la carpeta antigua `~/.ai-cycling-coach`. No se usan (tu perfil del 16-11 está en
`coach.db`), pero mejor quitarlos de en medio. Muévelos a la copia de seguridad que ya existe, sin borrarlos:

```bash
cd ~/dev/ai-cycling-coach-data
mkdir -p backup-json-viejos-12-11
mv profile.json settings.json backup-json-viejos-12-11/
```

## 1. Arrancar

```bash
./start.sh
```

La primera vez recompila (hay cambios en la interfaz y en el API Java) y pasa tus resúmenes de sesión a la base
de datos: en la terminal sale «Imported 4 session summaries…».

## 2. Sesiones

- [ ] Salen tus sesiones como antes, con su esfuerzo. Las de prueba (menos de 1 minuto) siguen escondidas, con el
  botón para verlas.
- [ ] Cambia el esfuerzo de una, recarga la página: sigue cambiado.
- [ ] «Más ▾ → Resumen (JSON)» descarga el resumen; «Descargar FIT» sigue funcionando.
- [ ] «Ver en replay» de una sesión con ruta dibuja la ruta.
- [ ] En `recordings/` ya no hay `session_*.json` (están en `backup-json-<fecha>/recordings/`).

## 3. Listas por páginas

Con tus datos solo el Historial tiene más de 20:

- [ ] **Historial**: 20 actividades y abajo «← Más recientes · 1–20 de 122 · Anteriores →». Pasa de página.
- [ ] Los botones de tipo (Bici, Carrera…) llevan cuántas hay y filtran de verdad (Carrera: 17).

## 4. Rutas

- [ ] Lista compacta: nombre, km, desnivel, pendiente máxima y «GRABADA» o «GENERADA».
- [ ] Al pinchar una se abre con su perfil y sus botones; «▴ cerrar» la cierra.
- [ ] Abre la página dos veces seguidas (o reinicia): abre al momento.
- [ ] «Generar una ruta → Como mi carrera» sigue ofreciendo tus 5 carreras.

## 5. Ajustes

- [ ] Arriba, dos pestañas: **Perfil** y **Rodillo y dispositivos**. Cada una con su dirección
  (`#/ajustes/perfil`, `#/ajustes/rodillo`): al recargar sigues en la misma.
- [ ] En el Panel, «elige cuál en Ajustes» (si hay varios dispositivos) lleva a la pestaña de dispositivos.
