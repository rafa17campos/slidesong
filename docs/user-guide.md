# Slidesong user guide

Slidesong turns a song and your Immich photos into a video whose photos follow the lyrics. You give it the song
and say whose photos and from when; it proposes a photo for every shot; you review and adjust; it makes the video.

*Versión en español: [user-guide.es.md](user-guide.es.md).*

## Home
- **New video**: give it a title; next come the song and the photos.
- Each card shows the project's step and what to do next («Upload the MP3», «Suggest photos», «Review the
  storyboard», «Watch the video»…). Versions of a project appear right after it.
- **The GPU computer** (top right), if there is one: *ready*, *busy* (new work waits until it is done) or *off*
  (jobs run on the server, more slowly).
- **Learning**: what the app has learned from your corrections (see [Learning](#learning)).
- **Backup**: download a copy of everything (see [Backups](#backups)).
- The language (English / Español) is chosen at the top.

A project has four steps, in the tabs at the top: **① Song → ② Photos → ③ Storyboard → ④ Video**. You can go back
and forth; the app opens each project where it makes sense.

## ① Song
1. **Upload MP3** (WAV, M4A, OGG and FLAC work too).
2. Paste the **lyrics**, one line per row. Suno tags such as `[Chorus]` or `[Bridge – Intimate]` mark the parts of
   the song: the app uses them for the pace and the transitions.
3. **Sung in**: the song's language, detected from the lyrics; change it if it is wrong.
4. **Analyze the song**: it finds the beat and the moment of each line (a couple of minutes), and splits the song
   into shots.

Then **Synced** shows each line with its moment, how it is read (an English translation and what a photo
illustrating it would show) and which shots it falls on. The subtitle icon next to a line puts that line on the
video (with «Subtitles: Chosen» in ② Photos). If you change the lyrics or the MP3, analyze again: the photos you had
chosen move to the new shots at the same moments.

## ② Photos
Which photos the app can use, and how it tells the story. Then **Suggest photos**.

- **Who's in them**: the people (from Immich) in the video. With none chosen, every photo from those dates counts.
- **When**: the dates (shortcuts: this summer, last 6 months, all of a year).
- **Theme** (optional): photos that match it come first (*beach, Christmas, birthday…*).
- **Avoid** (optional): photos that look like this drop way down (*beach, pool…*).
- **Immich album** (optional): its photos get priority. Handy to hand-pick a tray of photos in Immich first.
- **Sensitive photos** (shirtless, swimwear, diaper, bath…, from the photo tags): *suggest with a warning*, *avoid
  them* (only when nothing better fits) or *never suggest them*.
- **Pace**: *slow* (short lines share a photo), *normal* (about one photo per line), *fast* (two per line).
- **Photo order**: *by date, flexible* (a photo may move a few days to fit a line better), *strict* or *free*.
- **Camera movement**: *calm*, *normal* or *lively*.
- **Videos**: none, some (≈ 15 % of the shots) or plenty (≈ 35 %): short clips of your Immich videos, without sound.
- **Opening text** over the first shot, and **Subtitles**: off, all lines, or the ones you choose.
- **Learning**: use what the app learned from your corrections, or start from scratch for this project.
  **This project's settings** fine-tunes how much each thing counts here.

The panel on the right sums up the video (shots with a photo, pinned, videos, warnings) and the **candidate
photos**: how many there are and how many are analysed on the GPU (quality and tags). If you change settings after
suggesting, it reminds you: **Suggest again** keeps the photos you pinned and may change the rest.

## ③ Storyboard
Every shot as a card, grouped by the parts of the song, with its line. Click (or tap) a shot to open it in the editor
(a side panel on a computer, a full screen on a phone).

- **Show**: all, *with warnings*, *pinned*, *videos*, *subtitles*. **Review warnings** walks you through the shots
  that need a look: a sensitive photo, the same or a very similar photo twice, a movement that would pixelate.
- **Size**: cards with lyrics, or photos only.
- The bar at the top shows the song: click a part to jump to its shots.

**In the shot editor**
- **Play shot with music**: a few seconds of that shot as it will look.
- **Change photo**: the chooser (below). **Don't use**: takes the photo out of this video and puts another.
- **Pin** (📌): keeps this photo when you suggest again. Pinning also marks its warnings as reviewed.
- **Swap with another shot**: then tap the other shot. **Paste Immich link**: puts the photo you copied in Immich.
- **Why this photo**: the reasons (the line names a place or a month, smiling, favorite, from the album…) and its
  warnings.
- **Same burst**: other photos of the same moment; one tap to use another.
- **Camera**: the framing (zoom in or out, pan, whole photo, album print, two album prints, diptych with the next
  shot or with another photo) and **How much it moves** (green is safe; yellow and red ask more resolution than the
  photo has). Album prints carry a handwritten text (month and year by default; you can write your own).
- **Transition** into the next shot: automatic (with the reason) or the one you choose.
- **Photo details**: date, place, people, what the AI sees, and its quality.
- **More**: undo / redo and other actions.

**Change photo (the chooser)**
- Search (*beach, snow, cake…*) or paste an Immich link.
- **Dates**: around the same time, ± 2 weeks, ± 2 months, any date, or the project's album. **People**: who must be
  in it. **Sort by**: best for this shot, best-looking, closest in date, newest, oldest.
- Filters: hide photos already used, hide sensitive ones, only favorites, portrait or landscape, photos or videos.
- **Best matches** shows the photos that fit the line; **See all** every photo of those dates and people.
- At the top, the photos of the same burst.

Every change can be undone (Ctrl Z / Ctrl Shift Z, or the arrows at the top).

## ④ Video
- **Quick preview**: 360p, to check the storyboard in a couple of minutes.
- **Final video**: 1080p, 2K or 4K at 60 fps. The times shown are with the GPU computer; without it, it takes
  longer. If shots still have warnings, it tells you first.
- **Export for editing**: a zip for DaVinci Resolve, Premiere or Kdenlive (one clip per shot, the photos, the song,
  the timeline and the transitions); a README inside explains how to open it.
- The videos made appear in the list: play, download or delete them. If you change the storyboard after a video,
  it says that video is out of date.

## Projects: versions and locking
In the project's **⋯** menu:
- **Create a new version…**: a copy of the whole edit (song, photos, framing, texts, settings), without its videos,
  to try something different without touching the original.
- **Lock (finished)…**: keeps the project as it is: you can watch it and make videos, but not change it. *Unlock…*
  asks before.
- **Backup…** of this project, and **Delete project** (Immich photos are never touched).

## Learning
Every correction (changing a photo, *Don't use*, pinning) teaches the app which signals matter to you: smiles,
sharpness, the lyrics, favorites… The **Learning** page (from Home) shows:
- **What it has learned** and whether it is in use: it only applies once it guesses your choices clearly better than
  the factory settings. **Learn again** / **Start over…**.
- **How much each thing counts**: from *none* to *much more*, for every project. Each project can adjust it again in
  ② Photos → *This project's settings*.
- **Your corrections**, to remove the ones that were a test or a mistake, and **Projects**, to choose which ones
  teach the app.

What a video is *about* (summer, snow, beach) belongs to each project: its theme, dates and *Avoid*.

## Backups
**Backup** (Home, or a project's ⋯ menu) downloads a zip with the projects, their undo history and songs, what was
learned and the photo analysis; optionally the videos made. The photos stay in Immich. To restore it, see the README.

## Keyboard shortcuts (storyboard)
| Keys | Action |
|---|---|
| ← → · J K | Previous / next shot |
| Enter | Open the shot |
| Esc | Close |
| C | Change the photo |
| X | Don't use this photo |
| F | Pin / unpin |
| P | Play the shot with music |
| Ctrl Z / Ctrl Shift Z | Undo / redo |
| ? | Show the shortcuts |

## Tips
- Choose only the people the video is about: photos where only others appear count less.
- Write the lyrics with Suno's section tags: transitions follow the song's structure.
- Lines that name a month, a season, a place or a person pull photos that match.
- Make a quick preview before the final video, and pin the photos you are sure about before suggesting again.
- Without the GPU computer everything works except analysing new photos (quality and tags), and videos take
  longer.
