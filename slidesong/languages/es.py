"""Spanish: what Slidesong needs to read songs in Spanish and to speak it in the interface.

Copy this file as <code>.py (ISO 639-1) to add a language; the engine (slidesong/lexicon.py, slidesong/i18n.py)
finds it on its own. Words are written normalized: lower case, no accents.
"""

CODE = "es"
NAME = "Spanish"          # in English
NLLB = "spa_Latn"      # code for the CLIP text encoder and the local translator (NLLB-200)

# very common words, to tell the language of some lyrics
COMMON_WORDS = (
    "el la los las que de del y en un una por con para mi tu su se no es esta como mas pero muy todo nos lo "
    "al ya hay cuando donde quiero vamos"
)

# months, January first, as compared (normalized) and as written (album captions: «julio 2026»)
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
MONTH_NAMES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
# other spellings of a month
MONTH_ALIASES = {"setiembre": 9}
# months that are also everyday words: they only count with a capital letter mid-line
AMBIGUOUS_MONTHS = set()

# words for a season -> "summer", "autumn", "winter", "spring" or "christmas"
SEASONS = {"verano": "summer", "veranos": "summer", "otono": "autumn", "invierno": "winter", "primavera": "spring",
           "navidad": "christmas", "navidades": "christmas"}

# concept id (lexicon.CONCEPTS) -> word prefixes that name it (3 letters or less: the whole word; «=»: the whole
# word or its plural in -s; with a space: that phrase)
CONCEPTS = {"leaves": ("hoja",), "puddles": ("charco",), "rain": ("lluvia", "llover", "llovi", "llueve"),
           "snow": ("nieve", "nevar", "nevo"), "beach": ("playa", "arena"), "pool": ("piscina",),
           "sea": ("mar", "olas"), "birthday": ("vela", "tarta", "cumplean"), "presents": ("regalo",),
           "school": ("cole", "colegio", "clases", "escuela", "profe"), "backpack": ("mochila",),
           "boots": ("botas",), "bike": ("bici",), "playground": ("columpio", "tobogan"),
           "fair": ("feria", "atraccion", "noria"), "costume": ("disfraz",), "airplane": ("avion", "vuelo"),
           "train": ("tren",), "boat": ("barco", "barca"), "car": ("coche",), "grandparents": ("abuel",),
           "dog": ("perro", "perrito"), "cat": ("gato",), "horse": ("caballo", "poni"), "ice cream": ("helado",),
           "castle": ("castillo",), "mountain": ("montan", "monte"), "forest": ("bosque", "arbol"),
           "water": ("rio", "lago"), "camp": ("campamento", "tienda de campana"), "wind": ("viento",),
           "night": ("noche", "estrella", "luna"), "christmas": ("navidad", "reyes", "belen"), "flowers": ("flor",),
           "laughter": ("risa", "reia", "reir")}

# Immich's English country names -> how lyrics in this language name them
COUNTRIES = {"germany": "alemania", "france": "francia", "italy": "italia", "portugal": "portugal",
           "united kingdom": "inglaterra reino unido londres", "switzerland": "suiza", "austria": "austria",
           "netherlands": "holanda paises bajos", "belgium": "belgica", "united states": "estados unidos america",
           "morocco": "marruecos", "greece": "grecia", "ireland": "irlanda", "denmark": "dinamarca",
           "sweden": "suecia", "norway": "noruega", "spain": "espana"}

# generic words that are also parts of place names: never a match on their own
PLACE_STOP = set("""
de del la las el los y san santa santo playa puerto valle villa nueva nuevo real mayor monte sierra campo
puente castillo torre spain espana comunidad region provincia estacion barrio centro ciudad pueblo plaza casa casas
carretera camino urbanizacion poligono lago montana bosque isla cabo alto bajo viejo grande norte este oeste playas
molino venta cruz fuente huerta
""".split())

# Suno-style section tags ([Chorus – …]): words that name each kind in this language
SECTIONS = {"prechorus": ("pre-estribillo",), "chorus": ("estribillo", "coro"), "bridge": ("puente",),
            "outro": ("final", "fin"), "interlude": ("instrumental",), "verse": ("estrofa", "verso")}

# ---------------- the interface: the server's messages (English -> Spanish) ----------------
TEXTS: dict[str, str] = {
    # errors and refusals
    "Project not found": "Proyecto no encontrado",
    "The project is locked: unlock it (⋯ menu) or create a new version to change it":
        "El proyecto está bloqueado: desbloquéalo (menú ⋯) o crea una versión nueva para cambiarlo",
    "Wait until «{job}» finishes to change anything": "Espera a que termine «{job}» para cambiar nada",
    "Wait until «{job}» finishes": "Espera a que termine «{job}»",
    "A job is already running: {job}": "Ya hay un trabajo en marcha: {job}",
    "Invalid setting": "Ajuste no válido",
    "That correction is no longer there": "Esa corrección ya no está",
    "It is learning right now: wait until it finishes": "Está aprendiendo ahora: espera a que termine",
    "Wait until the running job finishes": "Espera a que termine el trabajo en marcha",
    "Give it a name": "Ponle un nombre",
    "You've made another change since: undo in order with ↶": "Ya has hecho otro cambio después: deshaz en orden con ↶",
    "Nothing to undo": "No hay nada que deshacer",
    "Nothing to redo": "No hay nada que rehacer",
    "A job is running": "Hay un trabajo en marcha",
    "Invalid album": "Álbum no válido",
    "Invalid margin": "Margen no válido",
    "Invalid video option": "Opción de vídeos no válida",
    "Invalid movement style": "Estilo de movimiento no válido",
    "Invalid subtitles option": "Opción de subtítulos no válida",
    "Invalid option": "Opción no válida",
    "Invalid order": "Orden no válido",
    "Invalid pace": "Ritmo no válido",
    "Invalid language": "Idioma no válido",
    "Audio format not supported": "Formato de audio no soportado",
    "That file doesn't look like a song that can be read": "Ese archivo no parece una canción que se pueda leer",
    "Upload the song first": "Sube primero la canción",
    "Analyze the song first": "Analiza primero la canción",
    "No photos chosen": "No hay fotos elegidas",
    "It's the same shot": "Es el mismo plano",
    "Can't find that photo in Immich (is it another user's?)": "No encuentro esa foto en Immich (¿es de otro usuario?)",
    "The photo of that shot had already changed": "La foto de ese plano ya había cambiado",
    "Invalid transition": "Transición no válida",
    "That shot doesn't exist": "Ese plano no existe",
    "Invalid movement": "Movimiento no válido",
    "That shot has no photo": "Ese plano no tiene foto",
    "Couldn't prepare the video": "No se pudo preparar el vídeo",
    "The interface is not built (cd frontend && npm run build)":
        "La interfaz no está compilada (cd frontend && npm run build)",
    # jobs: names, progress, errors (stored in the project)
    "Analyzing the song": "Analizando la canción",
    "Choosing photos": "Eligiendo fotos",
    "Making the video": "Montando el vídeo",
    "Preparing the editable project": "Preparando el proyecto editable",
    "Interrupted when Slidesong restarted": "Se interrumpió al reiniciarse Slidesong",
    "waiting for {worker}": "esperando a {worker}",
    "{worker} stopped responding": "{worker} dejó de responder",
    "{worker} refused the job: {detail}": "{worker} rechazó el trabajo: {detail}",
    "{worker}: {detail}": "{worker}: {detail}",
    "this server": "este servidor",
    "GPU computer": "el PC de la GPU",
    "no GPU worker": "sin worker de GPU",
    "chosen by you": "elegida por ti",
    "{reason} (short shot)": "{reason} (plano corto)",
    "Photos": "Fotos",
    "Shot": "Plano",
    "Immich ML is not responding: {detail}": "ML de Immich no responde: {detail}",
    "Can't read photo {id}": "No puedo leer la foto {id}",
    "Can't download video {id}": "No puedo descargar el vídeo {id}",
    "No photos assigned": "No hay fotos asignadas",
    "The edit plan is missing": "Falta el plan de montaje",
    "ffmpeg failed": "ffmpeg falló",
    "There are fewer photos ({n}) than shots ({m}); widen the dates or people":
        "Hay menos fotos ({n}) que planos ({m}); amplía fechas o personas",
    "No photos with those filters": "No hay fotos con esos filtros",
    "the worker is busy with another job": "el worker está ocupado con otro trabajo",
    "{script} failed: {detail}": "{script} falló: {detail}",
    "scorer not installed on this worker": "scorer no instalado en este worker",
    "tagger not installed on this worker": "tagger no instalado en este worker",
    # undo labels
    "suggest the photos": "sugerir las fotos",
    "change {what}": "cambiar {what}",
    "swap shots {a} and {b}": "intercambiar los planos {a} y {b}",
    "change the photo of shot {n}": "cambiar la foto del plano {n}",
    "don't use the photo of shot {n}": "no usar la foto del plano {n}",
    "choose the video clip of shot {n}": "elegir el trozo del vídeo del plano {n}",
    "pin the photo of shot {n}": "fijar la foto del plano {n}",
    "unpin the photo of shot {n}": "soltar la foto del plano {n}",
    "change shot {n}": "cambiar el plano {n}",
    "allow a photo again": "volver a permitir una foto",
    "change the transition after shot {n}": "cambiar la transición tras el plano {n}",
    "change the framing of shot {n}": "cambiar el encuadre del plano {n}",
    "change the second photo of shot {n}": "cambiar la segunda foto del plano {n}",
    "change the movement of shot {n}": "cambiar el movimiento del plano {n}",
    "change the photo's caption": "cambiar el texto de la foto",
    "add the subtitle of shot {n}": "poner el subtítulo del plano {n}",
    "remove the subtitle of shot {n}": "quitar el subtítulo del plano {n}",
    "add the subtitle of a line": "poner el subtítulo de una frase",
    "remove the subtitle of a line": "quitar el subtítulo de una frase",
    # why a photo («why» chips; emoji first)
    "🎵 fits the lyrics": "🎵 encaja con la letra",
    "🎵 somewhat fits the lyrics": "🎵 algo con la letra",
    "🗂️ from the album": "🗂️ del álbum",
    "⭐ favorite": "⭐ favorita",
    "😁 smiling": "😁 sonriendo",
    "🎨 good-looking": "🎨 bonita",
    "🎨 pretty": "🎨 bonita",  # its first English
    "👫 together": "👫 salen juntos",
    "🖼️ illustration": "🖼️ ilustración",
    "🎬 video ({s} s)": "🎬 vídeo ({s} s)",
    "🕒 by date": "🕒 por fecha",
    "🔍 small faces": "🔍 caras pequeñas",
    "😑 eyes closed": "😑 ojos cerrados",
    "💨 blurry face": "💨 cara desenfocada",
    "〰️ slightly soft face": "〰️ cara algo blanda",
    "💨 blurry": "💨 desenfocada",
    "〰️ slightly soft": "〰️ algo blanda",
    "🚫 looks like {what}": "🚫 parece {what}",
    "⚠️ {tag}": "⚠️ {tag}",
    "📅 {month}": "📅 {month}",
    "🔎 {what}": "🔎 {what}",
    "☀️ summer": "☀️ verano",
    "🍂 autumn": "🍂 otoño",
    "❄️ winter": "❄️ invierno",
    "🌸 spring": "🌸 primavera",
    "🎄 christmas": "🎄 navidad",
    # what the ML sees in a photo (insight.py, «Photo details»)
    "🏖️ beach": "🏖️ playa",
    "🏊 pool": "🏊 piscina",
    "🌊 sea": "🌊 mar",
    "🏞️ lake or river": "🏞️ lago o río",
    "⛰️ mountains": "⛰️ montaña",
    "🌲 forest": "🌲 bosque",
    "🌳 park": "🌳 parque",
    "🛝 playground": "🛝 parque infantil",
    "🎢 rides": "🎢 atracciones",
    "🎠 fair": "🎠 feria",
    "🦁 zoo or animals": "🦁 zoo o animales",
    "🐶 dog": "🐶 perro",
    "🐱 cat": "🐱 gato",
    "🐴 horse": "🐴 caballo",
    "🎂 birthday": "🎂 cumpleaños",
    "🎁 presents": "🎁 regalos",
    "🎭 costume": "🎭 disfraz",
    "🏫 school": "🏫 colegio",
    "🎒 first day of school": "🎒 primer día de cole",
    "📚 reading": "📚 leyendo",
    "🎨 painting": "🎨 pintando",
    "🧸 playing with toys": "🧸 jugando con juguetes",
    "🧱 building blocks": "🧱 construcciones",
    "📺 TV or screen": "📺 tele o pantalla",
    "🍝 eating": "🍝 comiendo",
    "🍦 ice cream": "🍦 helado",
    "🍳 cooking": "🍳 cocinando",
    "🛁 bath": "🛁 baño",
    "😴 sleeping": "😴 durmiendo",
    "👶 baby": "👶 bebé",
    "🤗 hug": "🤗 abrazo",
    "😂 laughing": "😂 risas",
    "😢 crying": "😢 llorando",
    "👨‍👩‍👦 family": "👨‍👩‍👦 familia",
    "👵 grandparents": "👵 abuelos",
    "🚗 car": "🚗 coche",
    "✈️ airplane": "✈️ avión",
    "🚆 train": "🚆 tren",
    "🚤 boat": "🚤 barco",
    "🚲 bike": "🚲 bici",
    "🛴 scooter": "🛴 patinete",
    "⚽ football": "⚽ fútbol",
    "🏀 sports": "🏀 deporte",
    "🏛️ city": "🏛️ ciudad",
    "⛪ monument": "⛪ monumento",
    "🏰 castle": "🏰 castillo",
    "🏠 at home": "🏠 en casa",
    "🛏️ in bed": "🛏️ en la cama",
    "🌅 sunset": "🌅 atardecer",
    "🌙 at night": "🌙 de noche",
    "☀️ sunny day": "☀️ día soleado",
    "🌧️ rain": "🌧️ lluvia",
    "☔ puddles": "☔ charcos",
    "❄️ snow": "❄️ nieve",
    "🌸 flowers": "🌸 flores",
    "🎈 balloons": "🎈 globos",
    "🎶 music": "🎶 música",
    "🏕️ camping": "🏕️ campamento",
    "🧗 adventure": "🧗 aventura",
    "🛒 shopping": "🛒 compras",
    "🍽️ restaurant": "🍽️ restaurante",
    "🎪 show": "🎪 espectáculo",
    "📄 screenshot or text": "📄 captura o texto",
    "🖼️ drawing or illustration": "🖼️ dibujo o ilustración",
    "🎃 halloween": "🎃 halloween",
    "🤳 selfie": "🤳 selfie",
    "🔗 chosen in Immich": "🔗 elegida en Immich",
    # transition reasons (the plan)
    "jump: {a} → {b}": "salto: {a} → {b}",
    "jump: {d} days later": "salto: {d} días después",
    "jump: {d} days earlier": "salto: {d} días antes",
    "same moment": "mismo momento",
    "the lyrics begin: the story opens": "empieza la letra: se abre la historia",
    "same moment: hard cut": "mismo momento: corte seco",
    "same moment, soft part": "mismo momento, parte suave",
    "intimate part": "parte íntima",
    "intimate part: soft blur": "parte íntima: desenfoque suave",
    "pause in the vocals": "pausa en la voz",
    "strong hit on the downbeat": "golpe fuerte al empezar compás",
    "chorus: cut on the beat": "estribillo: corte al golpe",
    "chorus: follows the movement": "estribillo: sigue el movimiento",
    "chorus: whip pan with the movement": "estribillo: barrido rápido con el movimiento",
    "short shots": "planos cortos",
    "verse": "estrofa",
    "verse: follows the movement": "estrofa: sigue el movimiento",
    "verse: the next one slides in on top": "estrofa: la siguiente entra encima",
    "verse: soft blur": "estrofa: desenfoque suave",
    "diptych with the next one": "díptico con el siguiente",
    # export (inside the zip)
    "Song": "Canción",
    "shot": "plano",
    "Cut": "Corte", "Fade": "Fundido", "Push": "Empuje", "Dip to white": "Fundido a blanco", "Dip to black": "Fundido a negro",
    "Flash": "Destello", "Zoom": "Zoom", "Slide over": "Deslizar encima", "Wipe": "Cortinilla", "Whip pan": "Barrido rápido",
    "Iris": "Círculo", "Blur": "Desenfoque", "Warm light": "Luz cálida", "Diptych": "Díptico",
    "Transitions the app chose (fades are already in the timeline as cross-dissolves; the rest are cuts, so you "
    "can add the effect you like in your editor).":
        "Transiciones que eligió la app (las de fundido ya van en la línea de tiempo como fundidos cruzados; "
        "las demás van como corte para que pongas el efecto que quieras de tu editor).",
}

# Section-change reasons, one sentence per section (Spanish needs the right article)
_SECTIONS = {  # kind: (English, Spanish with article)
    "intro": ("intro", "la intro"), "verse": ("verse", "la estrofa"), "prechorus": ("pre-chorus", "el pre-estribillo"),
    "chorus": ("chorus", "el estribillo"), "bridge": ("bridge", "el puente"), "outro": ("outro", "el final"),
    "interlude": ("instrumental", "el instrumental"),
}
for _en, _es in _SECTIONS.values():
    _es_noun = _es.split(" ", 1)[1]
    TEXTS[f"the {_en} comes in"] = f"entra {_es}"
    TEXTS[f"the {_en} comes in (strong hit)"] = f"entra {_es} (golpe fuerte)"
    TEXTS[f"the {_en} begins, more intimate"] = f"empieza {_es}, más íntimo"
    TEXTS[f"the {_en} begins, more intimate: warm light"] = f"empieza {_es}, más íntimo: luz cálida"
    TEXTS[f"the chorus ends, the {_en} is back"] = f"acaba el estribillo, vuelve {_es}"
    TEXTS[f"new {_en}"] = f"nueva {_es_noun}" if _es.startswith("la ") else f"nuevo {_es_noun}"
    TEXTS[f"new section: {_en}"] = f"nueva sección: {_es_noun}"


# Older Spanish texts whose English is now different (only read: never written again)
LEGACY: dict[str, str] = {
    "Se interrumpió al reiniciarse Montaje": "Interrupted when Slidesong restarted",
    "cambiar {what} del plano {n}": "change shot {n}",
    "cambiar del plano {n}": "change shot {n}",
}
for _en, _es in _SECTIONS.values():  # before the article fix: «empieza el estrofa», «entra el estribillo»…
    _noun = _es.split(" ", 1)[1]
    LEGACY[f"entra el {_noun}"] = f"the {_en} comes in"
    LEGACY[f"entra el {_noun} (golpe fuerte)"] = f"the {_en} comes in (strong hit)"
    LEGACY[f"empieza el {_noun}, más íntimo"] = f"the {_en} begins, more intimate"
    LEGACY[f"empieza el {_noun}, más íntimo: luz cálida"] = f"the {_en} begins, more intimate: warm light"
    LEGACY[f"acaba el estribillo, vuelve la {_noun}"] = f"the chorus ends, the {_en} is back"
    LEGACY[f"nueva {_noun}"] = f"new {_en}"

# Words that fill the placeholders ({month}, {tag}, {what}…), translated too
WORDS: dict[str, str] = {
    # months
    "January": "enero", "February": "febrero", "March": "marzo", "April": "abril", "May": "mayo", "June": "junio",
    "July": "julio", "August": "agosto", "September": "septiembre", "October": "octubre", "November": "noviembre",
    "December": "diciembre",
    # sensitive photos
    "shirtless": "sin camiseta", "in swimwear": "en bañador", "in a diaper": "en pañal", "in the bath": "en el baño",
    "belly showing": "tripa al aire",
    # what a lyric line names (suggest.CONCEPTS)
    "leaves": "hojas", "puddles": "charcos", "rain": "lluvia", "snow": "nieve", "beach": "playa", "pool": "piscina",
    "sea": "mar", "birthday": "cumpleaños", "presents": "regalos", "school": "cole", "backpack": "mochila",
    "boots": "botas", "bike": "bici", "playground": "parque", "fair": "feria", "costume": "disfraz",
    "airplane": "avión", "train": "tren", "boat": "barco", "car": "coche", "grandparents": "abuelos", "dog": "perro",
    "cat": "gato", "horse": "caballo", "ice cream": "helado", "castle": "castillo", "mountain": "montaña",
    "forest": "bosque", "water": "agua", "camp": "campamento", "wind": "viento", "night": "noche",
    "christmas": "navidad", "flowers": "flores", "laughter": "risas",
    # settings (undo labels: «change the theme»)
    "the title": "el título", "the opening text": "el texto del principio", "the people": "las personas",
    "the dates": "las fechas", "the theme": "el tema", "the pace": "el ritmo", "the lyrics": "la letra",
    "the album": "el álbum", "the order": "el orden", "the videos": "los vídeos", "the date margin": "el margen de fechas",
    "the learning": "el aprendizaje", "the sensitive photos": "las fotos sensibles", "the subtitles": "los subtítulos",
    "the movement": "el movimiento", "what to avoid": "lo que evitar", "this project's settings": "los ajustes de este proyecto",
    "the song's language": "el idioma de la canción",
    "GPU computer": "el PC de la GPU",
    # job names in messages («Wait until «Choosing photos» finishes»)
    "Analyzing the song": "Analizando la canción", "Choosing photos": "Eligiendo fotos",
    "Making the video": "Montando el vídeo", "Preparing the editable project": "Preparando el proyecto editable",
}