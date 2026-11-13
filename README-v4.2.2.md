# AI Cycling Coach v4.2.2 — Perfil FTMS exacto

Se revierte el suavizado visual de la pendiente de v4.2.1. La gráfica de REPLAY vuelve a mostrar exclusivamente **escalones** correspondientes a las órdenes FTMS registradas en la sesión: 1 %, 2 %, 3 %, 2 %, 0 %. Antes de la primera orden se muestra un intervalo desconocido, NO se inventa 0 %.

Se conservan sin modificaciones la grabación CSV, los gráficos progresivos, los controles Java/Python corregidos y la configuración de mandos de v4.2.1. Las marchas de REPLAY son virtuales; no modifican físicamente el KICKR. El perfil no es altitud medida ni control físico.

Instalación en carpeta independiente:

```sh
cd ~/dev/ai-cycling-coach-v4.2.2
bash init.sh --start
```

Este paquete NO ha sido compilado completamente ni probado con mandos BLE reales en el entorno de creación. Validar mediante `npm run build` en frontend y con los controles de REPLAY en el Mac.
