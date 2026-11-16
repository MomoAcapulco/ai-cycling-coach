# Probar la base de datos `coach.db` (fase 1)

Sin rodillo. Unos 5 minutos.

## 1. Arrancar

En la carpeta del proyecto:

```bash
./start.sh
```

La primera vez se crea `coach.db` en tu carpeta de datos y se copian las actividades de `history.db`.

## 2. Comprobar en la app

- [ ] **Historial**: las mismas actividades que antes (118 de Strava y las de la app), con su esfuerzo y su nota.
- [ ] **Historial → carga**: FTP, forma, fatiga y frescura (CTL, ATL y TSB) como antes.
- [ ] **Sesiones**: abre una y cambia su esfuerzo; al recargar la página sigue cambiado.
- [ ] **Panel**: arranca sin errores (en el simulador o en el replay).

## 3. Comprobar los ficheros

En otra terminal:

```bash
ls -la ~/dev/ai-cycling-coach-data/ | grep db
```

Deben salir `coach.db` (con `coach.db-wal` y `coach.db-shm` al lado, que son normales) y `history.db`, que no
cambia y queda como copia.

Y para ver qué se importó:

```bash
sqlite3 ~/dev/ai-cycling-coach-data/coach.db "SELECT key, value FROM meta WHERE key IN ('schema_version', 'legacy_history_imported'); SELECT source, COUNT(*) FROM activities GROUP BY source;"
```

Debe decir `schema_version` 1, cuántas actividades se copiaron de `history.db` y cuántas hay de cada origen.

## 4. Si algo va mal

- Para la app (Ctrl+C) y pásame lo que sale en la terminal.
- Tus datos siguen en `history.db` y en los JSON: no se ha borrado nada. Para volver a empezar la migración, basta con
  borrar `coach.db`, `coach.db-wal` y `coach.db-shm`: se crea otra vez al arrancar.
