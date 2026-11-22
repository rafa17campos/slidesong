# Guía de uso de Slidesong

Slidesong convierte una canción y tus fotos de Immich en un vídeo en el que las fotos siguen a la letra. Le das la
canción y le dices de quién y de cuándo son las fotos; propone una foto para cada plano; tú la revisas y ajustas;
y hace el vídeo.

*English version: [user-guide.md](user-guide.md).*

## Inicio
- **Nuevo vídeo**: ponle un título; después vienen la canción y las fotos.
- Cada tarjeta dice en qué paso está el proyecto y qué toca después («Subir el MP3», «Sugerir fotos», «Revisar el
  montaje», «Ver el vídeo»…). Las versiones de un proyecto salen justo detrás de él.
- **El PC de la GPU** (arriba a la derecha), si lo hay: *listo*, *ocupado* (lo nuevo espera a que termine) o
  *apagado* (los trabajos se hacen en el servidor, más despacio).
- **Aprendizaje**: lo que la app ha aprendido de tus correcciones (ver [Aprendizaje](#aprendizaje)).
- **Copia de seguridad**: descarga una copia de todo (ver [Copias de seguridad](#copias-de-seguridad)).
- El idioma (English / Español) se elige arriba.

Un proyecto tiene cuatro pasos, en las pestañas de arriba: **① Canción → ② Fotos → ③ Montaje → ④ Vídeo**. Puedes ir
y volver; la app abre cada proyecto donde tiene sentido.

## ① Canción
1. **Subir MP3** (también WAV, M4A, OGG y FLAC).
2. Pega la **letra**, una frase por línea. Las etiquetas de Suno como `[Chorus]` o `[Bridge – Intimate]` marcan las
   partes de la canción: la app las usa para el ritmo y las transiciones.
3. **Idioma**: el de la canción, detectado a partir de la letra; cámbialo si se equivoca.
4. **Analizar la canción**: busca el ritmo y el momento de cada frase (un par de minutos) y divide la canción en
   planos.

Después, **Sincronizada** enseña cada frase con su momento, cómo se entiende (traducción al inglés y qué foto la
ilustraría) y en qué planos cae. El icono de subtítulo junto a una frase la pone escrita en el vídeo (con
«Subtítulos: Elegidas» en ② Fotos). Si cambias la letra o el MP3, vuelve a analizar: las fotos que habías elegido
pasan a los planos nuevos del mismo momento.

## ② Fotos
Qué fotos puede usar la app y cómo se cuenta la historia. Luego, **Sugerir fotos**.

- **Quién sale**: las personas (de Immich) del vídeo. Sin nadie elegido, cuentan todas las fotos de esas fechas.
- **Cuándo**: las fechas (atajos: este verano, últimos 6 meses, todo un año).
- **Tema** (opcional): da prioridad a las fotos que encajen (*playa, navidad, cumpleaños…*).
- **Evitar** (opcional): las fotos que se parezcan a esto bajan mucho (*playa, piscina…*).
- **Álbum de Immich** (opcional): sus fotos tienen prioridad. Útil para preparar antes una bandeja de fotos en
  Immich.
- **Fotos sensibles** (sin camiseta, en bañador, en pañal, en el baño…, según las etiquetas de las fotos):
  *proponer y avisar*, *evitarlas* (solo si no hay nada mejor) o *no proponerlas nunca*.
- **Ritmo**: *pausado* (frases cortas comparten foto), *normal* (más o menos una foto por frase), *rápido* (dos por
  frase).
- **Orden de las fotos**: *por fecha, flexible* (una foto puede moverse unos días para encajar mejor), *estricto* o
  *libre*.
- **Movimiento de cámara**: *tranquilo*, *normal* o *dinámico*.
- **Vídeos**: sin vídeos, algunos (≈ 15 % de los planos) o bastantes (≈ 35 %): trozos cortos de tus vídeos de
  Immich, sin sonido.
- **Texto al empezar** sobre el primer plano, y **Subtítulos**: no, todas las frases o las que elijas.
- **Aprendizaje**: usar lo que la app ha aprendido de tus correcciones, o empezar desde cero en este proyecto.
  **Ajustes de este proyecto** afina cuánto cuenta cada cosa aquí.

El panel de la derecha resume el vídeo (planos con foto, fijadas, vídeos, avisos) y las **fotos candidatas**:
cuántas hay y cuántas están analizadas con la GPU (calidad y etiquetas). Si cambias ajustes después de sugerir, te
lo recuerda: **Volver a sugerir** respeta las fotos que fijaste y puede cambiar las demás.

## ③ Montaje
Todos los planos en tarjetas, agrupados por partes de la canción, con su frase. Pulsa un plano para abrirlo en el
editor (un panel lateral en el ordenador, la pantalla entera en el móvil).

- **Mostrar**: todos, *con aviso*, *fijados*, *vídeos*, *con subtítulo*. **Revisar avisos** te lleva por los planos
  que conviene mirar: una foto sensible, la misma foto (o una muy parecida) dos veces, un movimiento que pixelaría.
- **Tamaño**: tarjetas con letra, o solo fotos.
- La barra de arriba es la canción: pulsa una parte para ir a sus planos.

**En el editor del plano**
- **Ver plano con música**: unos segundos de ese plano tal como quedará.
- **Cambiar foto**: el selector (abajo). **No usar**: quita la foto de este vídeo y pone otra.
- **Fijar** (📌): mantiene esta foto al volver a sugerir. Fijar también da sus avisos por revisados.
- **Intercambiar con otro plano**: luego pulsa el otro plano. **Pegar enlace de Immich**: pone la foto que copiaste
  en Immich.
- **Por qué esta foto**: los motivos (la frase nombra un lugar o un mes, sonriendo, favorita, del álbum…) y sus
  avisos.
- **Misma ráfaga**: otras fotos del mismo momento; un toque para usar otra.
- **Cámara**: el encuadre (acercándose, alejándose, barrido, foto entera, foto de álbum, dos fotos de álbum, díptico
  con la siguiente o con otra foto) y **cuánto se mueve** (el verde es seguro; amarillo y rojo piden más resolución
  de la que tiene la foto). Las fotos de álbum llevan un texto a mano (mes y año por defecto; puedes escribir el
  tuyo).
- **Transición** al plano siguiente: automática (con su motivo) o la que elijas.
- **Ficha de la foto**: fecha, lugar, personas, lo que ve la IA y su calidad.
- **Más**: deshacer / rehacer y otras acciones.

**Cambiar foto (el selector)**
- Busca (*playa, nieve, tarta…*) o pega un enlace de Immich.
- **Fechas**: misma época, ± 2 semanas, ± 2 meses, cualquier fecha o el álbum del proyecto. **Personas**: quién tiene
  que salir. **Ordenar por**: mejor para este plano, más bonitas, más cerca de la fecha, más recientes, más
  antiguas.
- Filtros: ocultar las ya usadas, ocultar las sensibles, solo favoritas, verticales u horizontales, fotos o vídeos.
- **Las que encajan** enseña las fotos que van con la frase; **Ver todas**, todas las de esas fechas y personas.
- Arriba, las fotos de la misma ráfaga.

Cualquier cambio se puede deshacer (Ctrl Z / Ctrl Mayús Z, o las flechas de arriba).

## ④ Vídeo
- **Vista previa rápida**: 360p, para revisar el montaje en un par de minutos.
- **Vídeo final**: 1080p, 2K o 4K a 60 fps. Los tiempos que indica son con el PC de la GPU; sin él tarda más. Si
  quedan planos con aviso, te lo dice antes.
- **Exportar para editar**: un zip para DaVinci Resolve, Premiere o Kdenlive (un clip por plano, las fotos, la
  canción, la línea de tiempo y las transiciones); dentro, un README explica cómo abrirlo.
- Los vídeos hechos salen en la lista: verlos, descargarlos o borrarlos. Si cambias el montaje después de un
  vídeo, te avisa de que ese vídeo ya no está al día.

## Proyectos: versiones y bloqueo
En el menú **⋯** del proyecto:
- **Crear una versión nueva…**: una copia de todo el montaje (canción, fotos, encuadres, textos, ajustes), sin sus
  vídeos, para probar otra cosa sin tocar el original.
- **Bloquear (terminado)…**: lo guarda tal cual: se puede ver y hacer vídeos, pero no cambiar. *Desbloquear…* pide
  confirmación.
- **Copia de seguridad…** de este proyecto, y **Borrar el proyecto** (las fotos de Immich nunca se tocan).

## Aprendizaje
Cada corrección (cambiar una foto, *No usar*, fijar) le enseña a la app qué te importa: sonrisas, nitidez, la letra,
las favoritas… La página **Aprendizaje** (desde Inicio) enseña:
- **Lo aprendido** y si se está usando: solo se aplica cuando acierta tus elecciones claramente mejor que los
  ajustes de fábrica. **Aprender de nuevo** / **Empezar de cero…**.
- **Cuánto cuenta cada cosa**: de *nada* a *mucho más*, para todos los proyectos. Cada proyecto puede reajustarlo en
  ② Fotos → *Ajustes de este proyecto*.
- **Tus correcciones**, para quitar las que fueron una prueba o un error, y **Proyectos**, para elegir cuáles
  enseñan a la app.

De qué va un vídeo (verano, nieve, playa) es cosa de cada proyecto: su tema, sus fechas y *Evitar*.

## Copias de seguridad
**Copia de seguridad** (Inicio, o el menú ⋯ de un proyecto) descarga un zip con los proyectos, su historial de
deshacer y sus canciones, lo aprendido y el análisis de las fotos; si quieres, también los vídeos hechos. Las fotos
siguen en Immich. Para restaurarla, mira el README.

## Atajos de teclado (montaje)
| Teclas | Acción |
|---|---|
| ← → · J K | Plano anterior / siguiente |
| Intro | Abrir el plano |
| Esc | Cerrar |
| C | Cambiar la foto |
| X | No usar esta foto |
| F | Fijar / soltar |
| P | Ver el plano con música |
| Ctrl Z / Ctrl Mayús Z | Deshacer / rehacer |
| ? | Ver los atajos |

## Consejos
- Elige solo a las personas de las que va el vídeo: las fotos en las que solo salen otros cuentan menos.
- Escribe la letra con las etiquetas de sección de Suno: las transiciones siguen la estructura de la canción.
- Las frases que nombran un mes, una estación, un lugar o a una persona atraen fotos que encajan.
- Haz una vista previa antes del vídeo final, y fija las fotos de las que estés seguro antes de volver a sugerir.
- Sin el PC de la GPU todo funciona salvo analizar fotos nuevas (calidad y etiquetas), y los vídeos tardan más.
