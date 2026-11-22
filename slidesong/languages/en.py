"""English: what Slidesong needs to read songs in English.

Copy this file as <code>.py (ISO 639-1) to add a language; the engine (slidesong/lexicon.py, slidesong/i18n.py)
finds it on its own. Words are written normalized: lower case, no accents.
"""

CODE = "en"
NAME = "English"          # in English
NLLB = "eng_Latn"      # code for the CLIP text encoder and the local translator (NLLB-200)

# very common words, to tell the language of some lyrics
COMMON_WORDS = (
    "the and you to of in it is my me your we on with all for be that this so our love what when just oh "
    "can will now are"
)

# months, January first, as compared (normalized) and as written (album captions: «julio 2026»)
MONTHS = "january february march april may june july august september october november december"
MONTH_NAMES = "January February March April May June July August September October November December"
# other spellings of a month
MONTH_ALIASES: dict[str, int] = {}
# months that are also everyday words: they only count with a capital letter mid-line
AMBIGUOUS_MONTHS = {"may", "march"}

# words for a season -> "summer", "autumn", "winter", "spring" or "christmas"
SEASONS = {"summer": "summer", "summertime": "summer", "autumn": "autumn", "winter": "winter",
           "spring": "spring", "springtime": "spring", "christmas": "christmas", "xmas": "christmas"}

# concept id (lexicon.CONCEPTS) -> word prefixes that name it (3 letters or less: the whole word; «=»: the whole
# word or its plural in -s; with a space: that phrase)
CONCEPTS = {"leaves": ("leaf=", "leaves="), "puddles": ("puddle",), "rain": ("rain=", "rainy=", "raining="),
           "snow": ("snow",), "beach": ("beach", "sand="), "pool": ("pool=",), "sea": ("sea=", "ocean", "wave="),
           "birthday": ("birthday", "candle", "cake="), "presents": ("gift=",),
           "school": ("school", "class=", "teacher"), "backpack": ("backpack", "schoolbag"), "boots": ("boot=",),
           "bike": ("bike", "bicycle"), "playground": ("playground", "swing=", "slide="),
           "fair": ("fair=", "carousel", "rollercoaster"), "costume": ("costume",),
           "airplane": ("plane=", "flight=", "airplane"), "train": ("train=",), "boat": ("boat=", "ship=", "sail="),
           "car": ("car=",), "grandparents": ("grandma", "grandpa", "granny", "grandparent", "grandmother",
                                             "grandfather"),
           "dog": ("dog=", "puppy", "puppies"), "cat": ("cat=", "kitten"), "horse": ("horse", "pony"),
           "ice cream": ("ice cream", "icecream"), "castle": ("castle",), "mountain": ("mountain", "hill="),
           "forest": ("forest", "tree=", "woods="), "water": ("river", "lake="), "camp": ("camp=", "camping", "tent="),
           "wind": ("wind=", "windy="), "night": ("night=", "stars=", "moon="),
           "christmas": ("christmas", "xmas", "santa="), "flowers": ("flower",), "laughter": ("laugh",)}

# Immich's English country names -> how lyrics in this language name them
COUNTRIES = {}

# generic words that are also parts of place names: never a match on their own
PLACE_STOP = set("""
the new old saint north south east west lake river beach port city town village street road park hill mount
county state district center centre upper lower great little st
""".split())

# Suno-style section tags ([Chorus – …]): words that name each kind in this language
SECTIONS = {"prechorus": ("pre-chorus", "prechorus", "pre chorus"), "chorus": ("chorus", "hook"), "bridge": ("bridge",),
            "intro": ("intro",), "outro": ("outro", "end"), "interlude": ("interlude", "instrumental", "break", "solo"),
            "verse": ("verse",)}

# English is the language the server's messages are written in: nothing to translate
TEXTS: dict[str, str] = {}
WORDS: dict[str, str] = {}
