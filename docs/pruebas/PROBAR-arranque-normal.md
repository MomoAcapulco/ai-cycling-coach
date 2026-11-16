# Probar el arranque normal y Ajustes sin simulador

Sin rodillo. Unos 5 minutos (la primera vez, un par más: compila).

## 1. Arranque normal

```bash
./start.sh
```

- [ ] La primera vez sale «Building the Java API…» y «Building the interface…» y tarda un poco. Debe terminar sin
  errores y decir `Mode: normal`.
- [ ] Abre la app y recorre **todas las páginas**: cada una debe abrir enseguida, también la primera vez.
- [ ] Para (Ctrl+C) y arranca otra vez: ahora **no** debe compilar nada (no sale «Building…»).

Si la compilación falla, pásame lo que sale en la terminal. Para volver al modo de antes mientras tanto:

```bash
./start.sh --dev
```

## 2. Ajustes

- [ ] Ya no está «Fuente de datos» con las tarjetas de Rodillo real y Simulador.
- [ ] Si estás en un replay, arriba lo dice con «Salir del replay»; al pulsarlo pasa al rodillo real.
- [ ] «Control de marchas del rodillo» y «Captura Bluetooth en bruto» se ven siempre.

## 3. Tu `.env`

Tu `.env` tiene todavía `TRAINER_MODE=REPLAY` con una grabación de diagnóstico del 11-11. Mejor cámbialo a:

```bash
TRAINER_MODE=WAHOO
```

y borra la línea `REPLAY_FILE=…`. Los replays se abren desde Sesiones o Rutas.
