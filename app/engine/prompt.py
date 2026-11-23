"""Prompt -> style + warnings. Rule-based, no external model, no API keys."""
import re

# genre words weigh 3, feel words weigh 1
STYLES = {
    "cinematic":  dict(genre=["cinematic", "orchestral", "trailer", "film", "epic"], feel=["dramatic", "heroic", "grand"],
                       bpm=(80, 100), scale="minor", prog=[0, 5, 2, 6], drums="epic", pad="saw", lead="soft", key="D"),
    "lofi":       dict(genre=["lofi", "lo-fi", "chillhop"], feel=["chill", "study", "cozy", "mellow", "rainy"],
                       bpm=(68, 82), scale="dorian", prog=[1, 4, 0, 0], drums="lofi", pad="soft", lead="pluck", key="F"),
    "corporate":  dict(genre=["corporate", "business", "presentation"], feel=["optimistic", "inspiring", "motivational", "product", "launch", "uplifting"],
                       bpm=(100, 114), scale="major", prog=[0, 4, 5, 3], drums="pop", pad="saw", lead="pluck", key="C"),
    "electronic": dict(genre=["electronic", "edm", "techno", "house", "synthwave"], feel=["dance", "club", "synth", "futuristic", "tech"],
                       bpm=(120, 128), scale="minor", prog=[0, 5, 2, 6], drums="four", pad="saw", lead="pluck", key="A"),
    "acoustic":   dict(genre=["acoustic", "folk", "guitar", "unplugged"], feel=["warm", "gentle", "organic", "pop"],
                       bpm=(90, 104), scale="major", prog=[0, 4, 5, 3], drums="pop", pad="soft", lead="pluck", key="G"),
    "tense":      dict(genre=["tense", "suspense", "thriller", "horror"], feel=["dark", "anxious", "aggressive", "ominous", "menacing"],
                       bpm=(92, 108), scale="minor", prog=[0, 1, 0, 5], drums="epic", pad="saw", lead="soft", key="E"),
    "playful":    dict(genre=["playful", "quirky", "bouncy", "kids"], feel=["fun", "happy", "cheerful", "whimsical", "silly"],
                       bpm=(112, 124), scale="major", prog=[0, 3, 4, 0], drums="pop", pad="soft", lead="pluck", key="D"),
    "ambient":    dict(genre=["ambient", "meditation", "spa", "drone"], feel=["calm", "peaceful", "dreamy", "relaxing", "serene"],
                       bpm=(60, 72), scale="major", prog=[0, 5, 3, 4], drums="soft", pad="soft", lead="soft", key="E"),
    "rock":       dict(genre=["rock", "punk", "metal"], feel=["driving", "powerful", "sports", "energetic", "intense"],
                       bpm=(126, 140), scale="minor", prog=[0, 6, 5, 6], drums="rock", pad="saw", lead="pluck", key="E"),
    "jazz":       dict(genre=["jazz", "lounge", "swing", "bossa"], feel=["smooth", "sophisticated", "cafe"],
                       bpm=(92, 108), scale="dorian", prog=[1, 4, 0, 5], drums="lofi", pad="soft", lead="soft", key="D"),
}
DEFAULT_STYLE = "corporate"
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10]}

MOOD_ENERGY = [("calm", .2), ("intro", .2), ("soft", .2), ("quiet", .2), ("gentle", .25), ("peaceful", .2),
               ("outro", .25), ("fade", .2), ("verse", .5), ("groove", .6), ("tense", .55),
               ("build", .55), ("rising", .55), ("growing", .55), ("drop", .9), ("peak", .95), ("uplift", .9),
               ("climax", .95), ("exciting", .9), ("energetic", .9), ("epic", .9), ("finale", .95),
               ("final", .9), ("intense", .9), ("aggressive", .9)]
RAMP_WORDS = ("build", "rising", "growing", "crescendo", "swell")

CALM = {"calm", "peaceful", "gentle", "soft", "relaxing", "serene", "quiet"}
LOUD = {"aggressive", "intense", "angry", "heavy", "violent", "furious"}

ARTISTS = ["taylor swift", "beatles", "coldplay", "hans zimmer", "eminem", "drake", "beyonce", "beyoncé", "ed sheeran",
           "adele", "metallica", "daft punk", "imagine dragons", "billie eilish", "the weeknd", "michael jackson",
           "john williams", "ariana grande", "bts", "a.r. rahman", "ar rahman", "queen", "nirvana", "led zeppelin",
           "pink floyd", "bad bunny", "rihanna", "bruno mars", "mozart", "disney"]
STYLE_OF = re.compile(r"(in the style of|sounds? like|similar to|cover of|remix of|like the song|the song|in the vein of)\s+[\"'“]?[\w' .&-]{2,40}", re.I)
VOCAL_WORDS = re.compile(r"\b(vocals?|singing|singer|sing|lyrics|rap|rapper|choir|humming|spoken|voice|voices|chant)\b", re.I)

# tiny multilingual lexicon: foreign word -> english keyword
LEX = {
    "tranquilo": "calm", "calma": "calm", "relajante": "relaxing", "épico": "epic", "epico": "epic", "feliz": "happy",
    "alegre": "cheerful", "tenso": "tense", "tensión": "tense", "energético": "energetic", "enérgico": "energetic",
    "optimista": "optimistic", "oscuro": "dark", "suave": "soft", "música": "", "para": "", "un": "", "una": "",
    "calme": "calm", "épique": "epic", "joyeux": "happy", "tendu": "tense", "énergique": "energetic", "sombre": "dark",
    "doux": "soft", "ruhig": "calm", "episch": "epic", "fröhlich": "happy", "spannend": "tense", "dunkel": "dark",
    "शांत": "calm", "खुश": "happy", "तेज़": "energetic", "तेज": "energetic", "उत्साही": "energetic", "डरावना": "tense",
    "शानदार": "epic", "आरामदायक": "relaxing", "धीमा": "soft",
    "穏やか": "calm", "静か": "calm", "壮大": "epic", "楽しい": "happy", "緊張": "tense",
}
STOPWORDS = {"el", "la", "los", "de", "con", "para", "und", "der", "die", "das", "ist", "le", "les", "du", "des", "pour", "avec", "est", "una", "un"}


def energy_of(text: str, default=0.6):
    t = text.lower()
    hits = [e for w, e in MOOD_ENERGY if w in t]
    return (sum(hits) / len(hits)) if hits else default


def has_ramp(text: str) -> bool:
    return any(w in text.lower() for w in RAMP_WORDS)


def parse_prompt(prompt: str):
    warnings, flags = [], {}
    text = (prompt or "").strip()
    if not text:
        warnings.append({"code": "EMPTY_PROMPT", "message": "Empty prompt; used the default neutral style."})
    low = text.lower()

    # --- non-English -> lexicon
    letters = [c for c in text if c.isalpha()]
    non_ascii = sum(1 for c in letters if ord(c) > 127) / max(1, len(letters))
    words = re.findall(r"[^\s,.;:!?()\"']+", low)
    if non_ascii > 0.15 or sum(w in STOPWORDS for w in words) >= 2 or any(w in LEX for w in words):
        flags["non_english"] = True
        matched = [LEX[w] for w in words if w in LEX and LEX[w]]
        low = " ".join(matched) + " " + " ".join(w for w in words if w not in LEX)
        warnings.append({"code": "NON_ENGLISH_PROMPT",
                         "message": f"Prompt looks non-English; interpreted with a built-in keyword lexicon ({len(matched)} terms recognised)."
                                    + ("" if matched else " Nothing recognised, used the default style.")})

    # --- real artist / song references and vocals: strip, never imitate
    removed = []
    for m in STYLE_OF.finditer(low):
        removed.append(m.group(0))
    low = STYLE_OF.sub(" ", low)
    for a in ARTISTS:
        if re.search(r"\b" + re.escape(a) + r"\b", low):
            removed.append(a)
            low = re.sub(r"\b" + re.escape(a) + r"\b", " ", low)
    if removed:
        flags["artist_reference"] = True
        warnings.append({"code": "ARTIST_REFERENCE_IGNORED",
                         "message": "The prompt references real songs/artists. These were ignored; an original composition was generated.",
                         "details": {"removed": removed}})
    if VOCAL_WORDS.search(low):
        flags["vocals_requested"] = True
        low = VOCAL_WORDS.sub(" ", low)
        warnings.append({"code": "VOCALS_NOT_SUPPORTED",
                         "message": "Vocals were requested. This engine is instrumental only; no vocals or words are produced."})

    # --- style scoring
    scores = {}
    for name, st in STYLES.items():
        s = sum(3 for w in st["genre"] if w in low) + sum(1 for w in st["feel"] if w in low)
        scores[name] = s
    best = max(scores, key=lambda k: scores[k])
    style = best if scores[best] > 0 else DEFAULT_STYLE
    if scores[best] == 0 and text:
        warnings.append({"code": "VAGUE_PROMPT", "message": f"No style keywords recognised; used the neutral '{DEFAULT_STYLE}' style."})

    # --- contradictions
    tokens = set(re.findall(r"[a-z]+", low))
    if tokens & CALM and tokens & LOUD:
        flags["contradiction"] = True
        if scores[best] < 3:
            style = "tense"
        warnings.append({"code": "CONTRADICTORY_PROMPT",
                         "message": f"Prompt mixes calm and aggressive words. Resolved to a '{style}' style at medium energy; "
                                    "use `sections` for a calm-to-intense arc."})
    energy = 0.6 if flags.get("contradiction") else energy_of(low)
    return dict(style=style, preset=STYLES[style], energy=energy, ramp=has_ramp(low), flags=flags, warnings=warnings)
