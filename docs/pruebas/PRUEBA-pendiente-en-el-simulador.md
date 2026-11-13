# Probar la pendiente y el desnivel sin el rodillo (simulador)

En modo **Simulador** la aplicación tiene la misma carretera virtual que con el rodillo: puedes elegir pendientes y ver
cómo cambian la velocidad, la distancia, el perfil y el desnivel. **No toca ningún dispositivo.** La potencia es la
simulada (oscila entre unos 120 y 210 W).

## Arrancar

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

```sh
./start.sh
```

En el navegador, **Ajustes → Modo: Simulador → Guardar**, y vuelve al **Panel**.

## Qué probar

1. **Iniciar sesión** en el Panel.
2. En el panel **Pendiente**, pulsa varias veces **+0,5 %** o arrastra el deslizador al 6 % y suéltalo.
3. Fíjate en:
   - **Pendiente → Carretera** sube poco a poco según avanzas (1 % cada 20 m), no de golpe.
   - **Velocidad** baja en la subida («En la carretera virtual»), aunque la del rodillo simulado no cambie.
   - **Desnivel** sube y el **VAM** (metros por hora) aparece mientras subes.
   - **Perfil del recorrido**: la montaña se dibuja según la distancia, con colores por pendiente.
4. Pon una **bajada** (por ejemplo −3 %): la velocidad sube, la altitud baja y el desnivel no suma.
5. **Terminar** la sesión y mira en **Sesiones**: distancia, desnivel, VAM, W/kg y mejores esfuerzos.
6. En **Ajustes → Perfil**, cambia «Transición: metros por cada 1 %» (por ejemplo a 50) y vuelve a subir la
   pendiente: ahora tarda más metros en llegar.

## Qué me cuentas

- Si la transición te parece realista (¿20 m por cada 1 % es mucho, poco?).
- Si las gráficas se entienden y si echas algo en falta.
