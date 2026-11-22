// Every text of the interface: locales/<language>/<area>.json. English is the source and its files type the keys;
// any other language is a folder with the same files, found on its own (README: «Adding a language»).
import type en_common from "./locales/en/common.json";
import type en_home from "./locales/en/home.json";
import type en_learning from "./locales/en/learning.json";
import type en_backup from "./locales/en/backup.json";
import type en_project from "./locales/en/project.json";
import type en_song from "./locales/en/song.json";
import type en_video from "./locales/en/video.json";
import type en_photos from "./locales/en/photos.json";
import type en_chooser from "./locales/en/chooser.json";
import type en_storyboard from "./locales/en/storyboard.json";
import type en_terms from "./locales/en/terms.json";

export interface Resources {
  common: typeof en_common;
  home: typeof en_home;
  learning: typeof en_learning;
  backup: typeof en_backup;
  project: typeof en_project;
  song: typeof en_song;
  video: typeof en_video;
  photos: typeof en_photos;
  chooser: typeof en_chooser;
  storyboard: typeof en_storyboard;
  terms: typeof en_terms;
}

type Texts = Record<string, unknown>;
const files = import.meta.glob<Texts>("./locales/*/*.json", { eager: true, import: "default" });

/** language -> area -> texts */
export const resources: Record<string, Record<string, Texts>> = {};
for (const [path, data] of Object.entries(files)) {
  const m = path.match(/\/locales\/([^/]+)\/([^/]+)\.json$/);
  if (m) (resources[m[1]!] ??= {})[m[2]!] = data;
}

export const en = resources.en as unknown as Resources;
export const NAMESPACES = Object.keys(en) as (keyof Resources)[];
/** the interface languages: English first, then the others in alphabetical order */
export const LANGUAGE_CODES = [
  "en",
  ...Object.keys(resources)
    .filter((l) => l !== "en")
    .sort(),
];
