// Shapes returned by the FastAPI backend (slidesong/app.py). Only what the UI reads is typed.

export type JobKind = "analyze" | "suggest" | "render" | "export";
export type JobState = "running" | "done" | "error" | "cancelled";

export interface Job {
  state: JobState;
  progress: number;
  error: string | null;
  /** the machine it runs on (the GPU worker's name, or this server's) */
  where: string | null;
  /** on the GPU worker (true) or here (false) */
  remote?: boolean | null;
  /** waiting for the GPU worker to finish something else */
  waiting?: boolean;
  started?: string;
  finished?: string;
}

export interface Prep {
  state: "running" | "done" | "error" | null;
  total: number | null;
  done: number | null;
  error: string | null;
}

export interface Section {
  kind: string; // intro | verse | prechorus | chorus | bridge | outro ...
  label: string;
  mood?: string;
  build?: boolean;
}

export interface LineAI {
  english: string;
  visual: string;
  tags: string[];
  source: string;
}

export interface Line {
  text: string;
  start: number;
  end: number;
  match?: number;
  section?: Section;
  ai?: LineAI;
  /** shown as a subtitle in the "only the chosen ones" mode */
  sub?: boolean;
}

export interface Slot {
  start: number;
  end: number;
  lyric: string;
  line_idx?: number[];
  lyric_cont?: boolean;
  asset: string | null;
  locked?: boolean;
  why?: Record<string, string[]>;
  alts?: string[];
  burst?: string[];
  burst_best?: string;
  subs?: boolean;
  /** video clips: where the used part starts (absent = centre of the video) */
  clip_start?: number;
}

export interface Face {
  /** [x1, y1, x2, y2], fractions of the photo */
  box: [number, number, number, number];
  selected?: boolean;
  name?: string | null;
}

export interface Asset {
  id: string;
  date: string;
  fav: boolean;
  name: string;
  w: number;
  h: number;
  video?: boolean;
  duration?: number;
  aspect?: number;
  faces?: Face[];
}

export interface Shot {
  slots: number[];
  kind: string; // in | out | pan_lr | ... | diptych | polaroid | polaroid_pair | video
  look?: string;
  pair?: string;
  pair_from?: string;
  start: number;
  end: number;
  amp?: number;
  override?: string;
  /** the user's camera-move factor (0..1.5); absent = automatic */
  move?: number;
  /** slider zones in %: [stretches from, pixelates from]; null = never in 0..150 */
  zones?: [number | null, number | null];
  mag?: number;
  res_limited?: boolean;
  auto_pct?: number;
  split?: number;
  tilt_dir?: "up" | "down";
  captions?: string[];
  caption_auto?: boolean[];
  clip_start?: number;
  clip_end?: number;
  aspect?: number;
}

export interface Boundary {
  after_slot: number;
  kind: string;
  auto?: string;
  override?: boolean;
  beats?: number;
  dir?: string;
  dur?: number;
  reason?: string;
}

export interface PlanSection {
  slot: number; // first slot of the section
  kind: string;
  name: string; // English name (Verse, Chorus…); the interface names sections by kind
  label: string;
  mood?: "low" | "mid" | "high";
}

export type RepeatKind = "same" | "dup" | "burst" | "similar";

export interface Repeat {
  a: number;
  b: number;
  kind: RepeatKind;
  sim?: number;
}

export interface Plan {
  shots: Shot[];
  boundaries: Boundary[];
  inner?: Boundary[];
  sections?: PlanSection[];
  repeats?: Repeat[];
}

export interface RenderFile {
  file: string;
  quality?: string; // preview | final | final2k | final4k
  created?: string;
  size?: number;
  /** the project's edit_rev when it was made */
  rev?: number;
  /** hash of what the video is made of (compare with Project.video_hash) */
  vhash?: string;
}

export type Pace = "slow" | "normal" | "fast";
export type Order = "strict" | "flex" | "free";
export type VideosMode = "off" | "some" | "many";
export type Sensitive = "show" | "avoid" | "never";
export type Subtitles = "off" | "all" | "some";
export type Motion = "calm" | "normal" | "lively";

export interface Settings {
  title: string;
  title_overlay: string;
  people: string[];
  date_from: string | null;
  date_to: string | null;
  theme: string;
  pace: Pace;
  lyrics: string;
  album_id: string | null;
  order: Order;
  videos: VideosMode;
  flex_days: number;
  learned: boolean;
  shirtless: Sensitive;
  subtitles: Subtitles;
  motion: Motion;
  /** the language the song is sung in: "auto" (detected from the lyrics) or "es", "en"… */
  lyrics_lang: string;
  /** «Avoid»: what this project's photos should not look like ("playa, piscina") */
  avoid: string;
  /** this project's levels per signal, on top of the general ones (missing = «Normal») */
  tuning: Record<string, Level>;
}

export interface Song {
  file: string;
  name: string;
  duration: number;
  /** when it was uploaded (a new song may keep the same file name) */
  uploaded?: string;
  tempo?: number;
  beats?: number[];
}

export interface Project extends Partial<Settings> {
  id: string;
  /** the language detected in the lyrics (null: too little to tell) */
  lyrics_detected?: string | null;
  /** false: the project was taken out of the learning */
  teaches?: boolean;
  title: string;
  created: string;
  updated?: string;
  song: Song | null;
  lines: Line[];
  slots: Slot[];
  assets: Record<string, Asset>;
  excluded: string[];
  renders: RenderFile[];
  exports?: RenderFile[];
  jobs: Partial<Record<JobKind, Job>>;
  plan?: Plan;
  shot_overrides?: Record<string, string>;
  pair_overrides?: Record<string, string>;
  transition_overrides?: Record<string, string>;
  move?: Record<string, number>;
  // added by GET /api/projects/{pid}
  running: JobKind | null;
  cancelling: boolean;
  server_now: string;
  prep?: Prep;
  history?: { undo: string | null; redo: string | null };
  /** counts the user's edits (each undoable change, undo and redo) */
  edit_rev?: number;
  /** fingerprint of what the video would be made of now (see RenderFile.vhash) */
  video_hash?: string;
  /** blocked: kept as it is (edits refused; videos can still be made) */
  frozen?: { at: string } | null;
  /** the settings the last suggestion was made with */
  suggested_with?: Record<string, unknown>;
  /** the project this one is a version of */
  parent?: { id: string; title: string } | null;
}

export interface ProjectSummary {
  id: string;
  title: string;
  updated: string | null;
  cover: string | null;
  slots: number;
  renders: number;
  song: boolean;
  photos: number; // shots with a photo
  finals: number; // final videos made
  running: JobKind | null;
  progress: number | null;
  frozen: boolean;
  parent: string | null;
}

export interface Album {
  id: string;
  name: string;
  count: number;
}

export interface Learning {
  running?: boolean;
  updated?: string;
  /** the weights learning would use (also when not applied) */
  weights?: Record<string, number>;
  events?: number;
  corrections?: number;
  pairs?: number;
  applied?: boolean;
  acc_default?: number;
  acc_learned?: number;
}

export interface WorkerStatus {
  name: string;
  online: boolean;
  /** on, but working on something else (the job will wait for it) */
  busy?: boolean;
  info: Record<string, unknown> | null;
}

export interface Person {
  name: string;
  count: number | null;
  /** in how many projects this person was chosen */
  used: number;
}

export interface BurstPhoto {
  id: string;
  date: string | null;
  current: boolean;
  best?: boolean;
  q: number | null;
  why: string[];
}

export interface Partner {
  id: string;
  date: string | null;
  portrait: boolean;
  burst: boolean;
  sensitive: string | null;
  q: number | null;
  why: string[];
}

/** A photo offered in «Change photo» (/options, /search and /rank answer with these fields). */
export interface Candidate {
  id: string;
  date?: string | null;
  video?: boolean;
  why?: string[];
  fit?: number | null; // how well it fits the shot (higher = better)
  quality?: number | null;
  days?: number | null; // distance in days to the shot's date
  portrait?: boolean;
  landscape?: boolean;
  sensitive?: string | null;
  fav?: boolean;
  used?: boolean;
  rank?: number; // order given by the server (search relevance, suggestion order)
  burst?: boolean;
  duration?: number;
}

/** GET /api/projects/{pid}/assets/{aid}/analysis — what the app knows about a photo. */
export interface Analysis {
  id: string;
  date: string | null;
  file: string | null;
  camera: string | null;
  size: [number, number] | null;
  favorite: boolean;
  place: string[];
  latlon: [number, number] | null;
  faces: { name: string | null; box: [number, number, number, number] }[];
  nearby?: string[];
  ram_tags?: string[] | null;
  sensitive_tags?: string[];
  scores?: {
    aesthetic: number | null;
    faces: {
      name: string | null;
      smile: number | null;
      eyes_open: number | null;
      frontal: boolean;
      focus: number | null;
    }[];
  } | null;
  vector: boolean;
  tags?: { label: string; z: number }[];
  ref_count?: number;
  lyric?: string;
  lyric_pct?: number;
  lyric_ai?: LineAI | null;
}

/** GET /api/projects/{pid}/coverage */
export interface Coverage {
  pool: number; // candidate photos of the project's filters
  pending: number; // of them, not analysed on the GPU yet (no quality scores or no RAM++ tags)
  worker: boolean; // the GPU worker answers
  name: string;
  can_analyse: boolean; // and it has the scorer and the tagger
}

export interface BackupInfo {
  projects: number;
  /** bytes of a whole backup without the videos */
  size: number;
  videos_size: number;
  last: { made: string; videos: boolean; projects: number; size: number } | null;
}

/** How much a signal counts, set by hand: nothing, less, normal, more, much more. */
export type Level = -2 | -1 | 0 | 1 | 2;

export interface SignalInfo {
  key: string;
  default: number;
  /** what learning makes of it (null until it has enough corrections) */
  learned: number | null;
  /** the general level (every project) */
  level: Level;
}

export interface LearningProject {
  id: string;
  title: string | null;
  teaches: boolean;
  learned: boolean;
  tuning: Record<string, Level>;
  corrections: number;
  accepted: number;
  deleted?: boolean;
}

export interface LearningDetail {
  status: Learning;
  signals: SignalInfo[];
  projects: LearningProject[];
}

export interface LearningEvent {
  ts: string;
  project: string;
  title: string | null;
  slot: number;
  action: "set" | "reject" | "accept";
  source: string | null;
  new: string | null;
  old: string | null;
  lyric: string | null;
}
