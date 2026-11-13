# AI Cycling Coach v4.2.1 — Mandos y perfil redondeado

Esta versión completa habilita la lectura de los dos mandos Zwift registrados para este Mac en `.env` y `.env.example`. En modo `REPLAY` las pulsaciones `+` y `−` deben modificar **únicamente** la marcha visual de 1 a 24. No altera la velocidad medida ni manda resistencia al KICKR. Comprueba el estado CONNECTED de ambos mandos en la cabecera. Si otros programas tienen conectados los mandos, desconéctalos antes.

La gráfica del perfil tiene ahora una curva continua ilustrativa mediante suavizado amplio (aproximadamente 34 segundos de escala gaussiana). No representa altitud GPS ni cambia los valores de pendientes ordenadas. Los primeros cinco minutos siguen etiquetados como *sin orden registrada*, no como 0 %. Un checkbox permite mostrar u ocultar los **escalones reales de las órdenes FTMS**, que no se modifican.

## Instalar

Descomprime en `~/dev/ai-cycling-coach-v4.2.1`, detén la instancia anterior, y ejecuta:

```bash
cd ~/dev/ai-cycling-coach-v4.2.1
bash init.sh --start
```

Las identificaciones BLE están fijadas a los UUID conocidos de este Mac. Si se usan otros mandos u otro Mac hay que actualizar `.env`. Para desconectar los mandos, cambia `ZWIFT_ENABLED=false`. Los puertos existentes deben estar libres.

## Prueba rápida

1. Cabecera: Zwift izquierdo y derecho deben mostrar CONNECTED. Si figura SEARCHING, NOT_FOUND o ERROR, mira la terminal del adaptador.
2. Pulsa el botón físico `+` derecho y observa incremento visual de marcha 12 a 13 (o desde la marcha actual). Pulsa `−` izquierdo para bajar. El campo «Último botón» debe cambiar.
3. En la sección Perfil, desmarca «Ver órdenes FTMS exactas» para ver solo la curva, o márcalo para superponer los escalones reales de la grabación.

En ningún caso se envían comandos físicos de control FTMS desde REPLAY.
