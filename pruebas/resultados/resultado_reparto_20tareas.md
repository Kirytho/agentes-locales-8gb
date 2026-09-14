# Reparto entre slots, las 20 tareas: la calidad no cambia, el tiempo se reduce a la mitad (12/09/2026)

Continuación de `resultado_reparto_proyecto.md`, que medía 4 tareas pequeñas. Aquí
están las 20 de ProjectEval, incluidas las de 19 piezas, con 2 repeticiones por
brazo. 120 proyectos generados y juzgados.

```
modelo    K2-Horizon-7B-Q4_K_S · ctx 32.768 · --parallel 4 --kv-unified
salida    max_tokens 8.000 (subido de 4.000: con 19 piezas, 4.000 era injusto
          con el monolito, que las escribe todas en una respuesta)
oráculo   el del banco: inicia el proyecto Django y lo opera con Selenium
```

## Generación

```
brazo         fallos    segundos   llamadas   tokens
monolito      14/40      1.054,9         40    59.824
secuencial    10/40      7.470,5        264   285.120
paralelo      10/40      2.984,3        264   207.757
```

**El paralelo iguala al secuencial en fallos haciendo las MISMAS 264 llamadas en
2,5 veces menos tiempo.** Los tiempos del secuencial entre repeticiones fueron
3.724,5 y 3.746,0 s —0,6% de diferencia—, así que la ventaja no es ruido.

El mecanismo se ve en los slots: durante el secuencial, 1 de 4 ocupado; durante
el paralelo, 4 de 4. Es la misma GPU trabajando completa en vez de un cuarto.

## Juicio

```
brazo         r1    r2    total     score
monolito      25    29   54/568    0,0951
paralelo      26    26   52/568    0,0915
secuencial    26    26   52/568    0,0915

Fisher:  monolito vs secuencial  p = 0,919
         monolito vs paralelo    p = 0,919
         secuencial vs paralelo  p = 1,000
```

**Repartir no cambia la calidad, ni siquiera con tareas de 19 piezas.** Era la
hipótesis que seguía abierta del informe anterior —que con tareas grandes
aparecería el costo de que dos trabajadores no se vean— y no apareció.

El monolito falla más DURANTE la generación (14 de 40 contra 10), pero los
proyectos que llega a entregar funcionan igual de bien. Sus fallos se concentran
en las tareas grandes: las tres de 13-19 piezas fallaron las tres en r1, y la 13
de forma extrema —19 piezas, 16 devueltas sin escribir, resuelta en 27 s y
1.522 tokens—. No es falta de capacidad sino abandono temprano: la tarea 12 (13
piezas) le tomó 54,6 s y 3.139 tokens y salió casi completa.

## Dónde queda el modelo

Usamos el esqueleto, así que el nivel comparable es **Direct-Level3**, no Level1
(el informe anterior lo comparaba mal):

| modelo | score |
|---|---:|
| GPT-3.5-turbo | 0,0528 |
| Gemini-2.0-flash | 0,0775 |
| Gemini-1.5-pro | 0,0824 |
| **K2-Horizon-7B (local, 8 GB)** | **0,0927** |
| GPT-4o | 0,1014 |

**ATENCIÓN: EL NÚMERO ESTÁ INFLADO Y NO ES UN EMPATE LIMPIO.** Nuestro prompt da
más que el banco original: enunciado + lista de verificación + **la lista de ids
de HTML esperados**. Esa última ayuda se añadió para que el brazo paralelo no
perdiera por construcción (los ids no están en el esqueleto y sin ellos cada
trabajador inventa los suyos), y los modelos del leaderboard no la tuvieron.
Cuánto pesa esa ventaja no se midió. Lo honesto es decir que el K2-7B **está en
ese nivel**, no que supera a Gemini.

Para un número comparable habría que ejecutar sin `_elementos_esperados`,
sabiendo que eso perjudica al paralelo más que a los otros dos brazos.

## Consecuencia para el intermediario

Repartir entre slots **no degrada y ahorra la mitad del tiempo**. Si el
intermediario divide una tarea en piezas y las envía a los 4 slots, gana velocidad
sin sacrificar calidad. El límite conocido sigue siendo otro: esto son llamadas
sueltas con prompt mínimo, no subagentes de un harness —un subagente de Hermes
arrastra ~5.657 tokens de prompt propio y por eso el abanico agota la reserva de
KV—.

## Pendientes

- Ejecutar sin la lista de ids, para un número comparable con el leaderboard.
- El juez **no cierra lo que abre**: deja un Django y un Chrome por proyecto.
  Con 120 proyectos se acumularon bastantes; hubo que cerrar `manage.py runserver`
  a mano. Conviene que el banco lo haga solo al terminar.
- Tercera repetición, si alguna vez importa una diferencia pequeña.
