"""Export a project for editing in another app (DaVinci Resolve, Premiere, Final Cut, Kdenlive...).

The package (a zip) holds one video file per shot with its camera move already done (plus half a second of
handle at each end, so the editor can lay its own transitions), the original photos, the song and the timeline
written by OpenTimelineIO as .otio (Kdenlive, Resolve) and FCP 7 XML (Premiere, Resolve). Media paths are
relative to the package (it can be unzipped anywhere), so an editor may ask to relink them once.
(FCPXML was left out: Final Cut needs absolute paths.) Fades become cross dissolves; the other transitions are left as cuts and listed
in transitions.txt with the app's choice, so they can be redone with the editor's own effects.
"""
import json
import zipfile
from pathlib import Path

import opentimelineio as otio
from .i18n import lang, localize, tr

FPS = 30
DISSOLVES = {"fade", "dipwhite", "dipblack", "blur", "light", "zoom"}  # all closest to a cross dissolve


def _t(seconds):
    return otio.opentime.RationalTime(round(seconds * FPS), FPS)


def _range(start_s, dur_s):
    return otio.opentime.TimeRange(_t(start_s), _t(dur_s))


def timeline(project, clips, song_name, song_duration, title):
    """OTIO timeline: the shot clips on a video track (cross dissolves where the app fades) and the song."""
    tl = otio.schema.Timeline(name=title)
    tl.global_start_time = otio.opentime.RationalTime(0, FPS)
    video = otio.schema.Track(name=tr("Photos"), kind=otio.schema.TrackKind.Video)
    audio = otio.schema.Track(name=tr("Song"), kind=otio.schema.TrackKind.Audio)
    bounds = {b["after_slot"]: b for b in (project.get("plan") or {}).get("boundaries", [])}
    pos = 0.0
    for n, c in enumerate(clips):
        if c["start"] > pos + 1e-3:
            video.append(otio.schema.Gap(source_range=_range(0, c["start"] - pos)))
        ref = otio.schema.ExternalReference(target_url=f"media/{c['file']}",
                                            available_range=otio.opentime.TimeRange(_t(0), otio.opentime.RationalTime(c["frames"], FPS)))
        lyric = " / ".join(dict.fromkeys(project["slots"][i].get("lyric") or "" for i in c["slots"])).strip(" /")
        clip = otio.schema.Clip(name=f"{tr('Shot')} {c['slots'][0] + 1}" + (f" · {lyric}" if lyric else ""), media_reference=ref,
                                source_range=_range(c["head"], c["end"] - c["start"]))
        video.append(clip)
        pos = c["end"]
        b = bounds.get(c["slots"][-1])
        if b and n + 1 < len(clips) and b["kind"] in DISSOLVES and b.get("dur"):
            half = min(b["dur"] / 2, c["tail"], clips[n + 1]["head"])
            if half >= 1 / FPS:
                video.append(otio.schema.Transition(transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                                                    in_offset=_t(half), out_offset=_t(half), name=b["kind"]))
    song_ref = otio.schema.ExternalReference(target_url=f"media/{song_name}", available_range=_range(0, song_duration))
    audio.append(otio.schema.Clip(name=tr("Song"), media_reference=song_ref, source_range=_range(0, song_duration)))
    tl.tracks.append(video)
    tl.tracks.append(audio)
    return tl


def transitions_table(project, clips):
    """Plain-text list of every cut with the transition the app chose (to redo it in the editor)."""
    from .plan import transition_name
    bounds = {b["after_slot"]: b for b in (project.get("plan") or {}).get("boundaries", [])}
    rows = [tr("Transitions the app chose (fades are already in the timeline as cross-dissolves; the rest are cuts, "
               "so you can add the effect you like in your editor)."), ""]
    for n, c in enumerate(clips[:-1]):
        b = bounds.get(c["slots"][-1])
        if not b:
            continue
        m, s = divmod(c["end"], 60)
        rows.append(f"{int(m)}:{s:05.2f}  {tr('shot')} {c['slots'][-1] + 1} → {clips[n + 1]['slots'][0] + 1}: "
                    f"{transition_name(b['kind'])} ({b.get('dur', 0):.2f} s) · {localize(b.get('reason', ''))}")
    return "\n".join(rows) + "\n"


README_EN = """Editable project: “{title}”
=============================

Contents
- media/shot_XXX.mp4: one video per shot, with its camera movement and half a second of margin at the start
  and at the end (so the editor can make transitions).
- media/{song}: the song.
- photos/: the original photos of each shot, in case you want to redo one your way.
- timeline.xml / .otio: the timeline with the shots in place and the music.
- transitions.txt: the transition the app chose at each cut.
- subtitles.srt (if you chose subtitles): the lyrics with their timing; import it as a subtitle track.
  The clips have no burned-in subtitles, so you can change their style in the editor.

How to open it (unzip it wherever you like first and don't move anything inside)
- DaVinci Resolve (free): File › Import › Timeline… › timeline.xml.
  If the shots show up in red ("offline"): select them all in the media pool,
  right click › Relink Clips… and choose the media folder.
- Premiere Pro: File › Import… › timeline.xml. If it asks to locate files, find one in the media
  folder and it will link the rest by itself.
- Kdenlive (free): File › Import › OpenTimelineIO project… › timeline.otio
- Anything else (CapCut included): drag the videos in media in order (shot_001, 002…) and the song;
  each video lasts its shot plus 1 s of margin: trim half a second off each side.

Not in the timeline: the opening text and the effects that are not fades (pushes, whip pans, flashes…),
which have their equivalents in any editor.
"""

README_ES = """Proyecto editable de «{title}»
=============================

Contenido
- media/shot_XXX.mp4: un vídeo por plano, ya con su movimiento de cámara y medio segundo de margen
  al principio y al final (para que el editor pueda hacer transiciones).
- media/{song}: la canción.
- photos/: las fotos originales de cada plano, por si quieres rehacer alguno a tu manera.
- timeline.xml / .otio: la línea de tiempo con los planos en su sitio y la música.
- transitions.txt: qué transición eligió la app en cada corte.
- subtitles.srt (si elegiste subtítulos): la letra con sus tiempos; impórtalo como pista de subtítulos.
  Los clips van sin subtítulos grabados para que puedas cambiar su estilo en el editor.

Cómo abrirlo (descomprime antes el zip donde quieras y no muevas nada de dentro)
- DaVinci Resolve (gratis): Archivo › Importar › Línea de tiempo… › timeline.xml.
  Si los planos salen en rojo («offline»): en el panel de medios selecciónalos todos,
  botón derecho › Volver a vincular clips… y elige la carpeta media.
- Premiere Pro: Archivo › Importar… › timeline.xml. Si pide localizar archivos, busca uno
  en la carpeta media y enlazará los demás solo.
- Kdenlive (gratis): Archivo › Importar › Proyecto OpenTimelineIO… › timeline.otio
- Cualquier otro (CapCut incluido): arrastra los vídeos de media en orden (shot_001, 002…) y la canción;
  cada vídeo dura lo que su plano más 1 s de margen, recórtalo medio segundo por cada lado.

Lo que no va en la línea de tiempo: el texto del principio y los efectos que no son fundidos
(empujes, barridos, destellos…), que tienen sus equivalentes en cualquier editor.
"""


def srt(subs):
    """SubRip text for [{start, end, text}]."""
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{n}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n" for n, s in enumerate(subs, 1))


def write_package(zip_path, project, clips_dir, clips, song_path, photos, title, subs=()):
    """photos: [(filename, bytes)]. Writes the zip; returns its path."""
    song_name = "song" + Path(song_path).suffix
    tl = timeline(project, clips, song_name, project["song"]["duration"], title)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:  # media is already compressed
        for c in clips:
            z.write(Path(clips_dir) / c["file"], f"media/{c['file']}")
        z.write(song_path, f"media/{song_name}")
        for name, data in photos:
            z.writestr(f"photos/{name}", data)
        z.writestr("timeline.otio", otio.adapters.write_to_string(tl, "otio_json"))
        z.writestr("timeline.xml", otio.adapters.write_to_string(tl, "fcp_xml"))
        z.writestr("transitions.txt", transitions_table(project, clips))
        if subs:  # the lyric subtitles chosen in the app, to import as a subtitle track
            z.writestr("subtitles.srt", srt(subs))
        z.writestr("README.txt", (README_ES if lang() == "es" else README_EN).format(title=title, song=song_name))
        z.writestr("clips.json", json.dumps(clips, ensure_ascii=False, indent=1))
    return zip_path
