import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpDown,
  Calendar,
  ChevronDown,
  ExternalLink,
  Film,
  Info,
  ListFilter,
  Plus,
  Search,
  Sparkles,
  Star,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ClipboardEvent } from "react";
import { Trans, useTranslation } from "react-i18next";

import { api, assetUrl } from "@/api/client";
import { useConfig, usePeople } from "@/api/queries";
import { useUndoToast } from "@/hooks/useUndoToast";
import type { Candidate, Project } from "@/api/types";
import { Dialog } from "@/components/ui/Dialog";
import { useToast } from "@/components/ui/Toast";
import {
  activeFilters,
  chooserView,
  DAYS,
  daysHint,
  daysLabel,
  DEFAULT_SHOW,
  sortName,
  type Days,
  type Show,
  type Sort,
} from "@/lib/chooser";
import { locale } from "@/i18n";
import { isQualityWarning, SECTION_COLOR, sectionName } from "@/lib/names";
import { fmtTime, type Group } from "@/lib/storyboard";

import { immichIdFrom, useBurst, usePartners, useShotActions } from "./actions";

const PAGE = 120;

export type ChooserMode = "change" | "pair";

const fmtDay = (d?: string | null) =>
  d ? new Date(d).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "2-digit" }) : "";

/**
 * "Change photo" (and "Second photo"): search or paste an Immich link, the burst on top, filters for dates,
 * people, order and what to show, and the photos as large thumbnails; a tap puts the photo in the shot.
 */
export function Chooser({
  project: p,
  i,
  mode,
  group,
  onClose,
  onInfo,
}: {
  project: Project;
  i: number | null;
  mode: ChooserMode;
  group?: Group;
  onClose: () => void;
  onInfo?: (id: string, slot: number) => void;
}) {
  return (
    <Dialog
      open={i != null}
      onClose={onClose}
      className="chooser"
      headClassName="ch-head"
      bodyClassName="ch-body"
      title={i != null ? <Title project={p} i={i} mode={mode} group={group} /> : ""}
    >
      {i != null && (
        <ChooserBody key={`${mode}-${i}`} project={p} i={i} mode={mode} onClose={onClose} onInfo={onInfo} />
      )}
    </Dialog>
  );
}

function Title({
  project: p,
  i,
  mode,
  group,
}: {
  project: Project;
  i: number;
  mode: ChooserMode;
  group?: Group;
}) {
  const { t } = useTranslation("chooser");
  const s = p.slots[i]!;
  return (
    <div className="ttl">
      <h2 id="ch-t">
        {t(mode === "pair" ? "title.pair" : "title.change", { n: i + 1 })}{" "}
        <span className="muted tnum" style={{ fontWeight: 500, fontSize: 15 }}>
          {fmtTime(s.start)}–{fmtTime(s.end)}
        </span>
      </h2>
      <div className="text-small" style={{ marginTop: 2 }}>
        {group?.section && (
          <span className="sec-pill" style={{ ["--c" as string]: SECTION_COLOR[group.section.kind] }}>
            {sectionName(group.section)}
          </span>
        )}{" "}
        {s.lyric && s.lyric !== "♪" && <q>{s.lyric}</q>}
      </div>
    </div>
  );
}

function ChooserBody({
  project: p,
  i,
  mode,
  onClose,
  onInfo,
}: {
  project: Project;
  i: number;
  mode: ChooserMode;
  onClose: () => void;
  onInfo?: (id: string, slot: number) => void;
}) {
  const { t } = useTranslation("chooser");
  const s = p.slots[i]!;
  const act = useShotActions(p.id);
  const toast = useToast();
  const { data: config } = useConfig();
  const { data: allPeople } = usePeople();

  const [q, setQ] = useState("");
  const [query, setQuery] = useState(""); // the search actually run
  const [days, setDays] = useState<Days>("same");
  // people named in the line join the filter («With Nico and Lía»), unless the user changes it
  const named = useMemo(() => namedIn(s.lyric, allPeople ?? []), [s.lyric, allPeople]);
  const [peopleSet, setPeople] = useState<string[] | null>(null);
  const people = peopleSet ?? [...(p.people ?? []), ...named.filter((n) => !p.people?.includes(n))];
  const [all, setAll] = useState(false);
  const [sort, setSort] = useState<Sort>("fit");
  const [show, setShow] = useState<Show>(DEFAULT_SHOW);
  const [shown, setShown] = useState(PAGE);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const sideRef = useRef<HTMLElement>(null);
  // phone: a chip opens the filters at its own section (they are a long column above the photos)
  const openFilter = (k: "days" | "people" | "sort" | "show") => {
    setFiltersOpen(true);
    requestAnimationFrame(() =>
      sideRef.current?.querySelector(`[data-filter="${k}"]`)?.scrollIntoView({ block: "start" }),
    );
  };
  // desktop: straight to the search box; phones: no keyboard popping up over the photos
  const [fine] = useState(() => window.matchMedia("(pointer: fine)").matches);

  const samePeople = people.length === (p.people ?? []).length && people.every((n) => p.people?.includes(n));
  const source: "alts" | "options" | "search" | "partners" =
    mode === "pair"
      ? "partners"
      : query
        ? "search"
        : days === "same" && samePeople && !all
          ? "alts"
          : "options";
  const effSort: Sort = source === "search" && sort === "fit" ? "query" : sort;

  // ---- data ----
  const altIds = useMemo(() => (s.alts ?? []).filter((a) => !p.excluded.includes(a)), [s.alts, p.excluded]);
  const alts = useQuery({
    queryKey: ["choose-alts", p.id, i, altIds],
    queryFn: async () => {
      const got = altIds.length
        ? await api.post<Candidate[]>(`/api/projects/${p.id}/slots/${i}/rank`, { ids: altIds })
        : [];
      const by = new Map(got.map((x) => [x.id, x]));
      return altIds.map((id, n) => ({ ...by.get(id), id, why: s.why?.[id] ?? by.get(id)?.why, rank: n }));
    },
    enabled: source === "alts",
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const dayValue = DAYS.find((d) => d.id === days)!.value;
  const options = useQuery({
    queryKey: ["choose-options", p.id, i, samePeople ? null : people, dayValue, all],
    queryFn: () =>
      api.post<Candidate[]>(`/api/projects/${p.id}/slots/${i}/options`, {
        people: samePeople ? null : people,
        days: dayValue,
        all,
      }),
    enabled: source === "options",
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const search = useQuery({
    queryKey: ["choose-search", p.id, i, query, people, days !== "any"],
    queryFn: () => {
      const qs = new URLSearchParams({
        q: query,
        slot: String(i),
        only_people: String(people.length > 0),
        only_dates: String(days !== "any"),
      });
      for (const n of people) qs.append("people", n);
      return api.get<Candidate[]>(`/api/projects/${p.id}/search?${qs}`);
    },
    enabled: source === "search",
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const partners = usePartners(p.id, i, mode === "pair");
  const current = { alts, options, search, partners }[source];
  const items: Candidate[] = useMemo(() => {
    if (source === "partners")
      return (partners.data ?? []).map((x, n) => ({ ...x, quality: x.q, landscape: !x.portrait, rank: n }));
    const raw = current.data ?? [];
    return source === "search" ? raw.map((x) => ({ ...x, why: [`🔎 ${query}`, ...(x.why ?? [])] })) : raw;
  }, [source, partners.data, current.data, query]);
  const { visible, hidden } = useMemo(() => chooserView(items, effSort, show), [items, effSort, show]);
  const usedAt = useMemo(() => new Map(p.slots.map((x, k) => [x.asset, k])), [p.slots]);

  // ---- actions ----
  const undoToast = useUndoToast(p.id);
  const done = (text: string, result?: unknown) => {
    onClose();
    undoToast(text, result);
  };
  const fail = (e: Error) => toast({ text: e.message, tone: "error" });
  const put = (x: Candidate, src: string = source) => {
    if (mode === "pair")
      return act.pair.mutate(
        { i, asset: x.id },
        { onSuccess: (r) => done(t("done.pair", { n: i + 1 }), r), onError: fail },
      );
    act.slot.mutate(
      {
        i,
        change: {
          action: "set",
          asset: x.id,
          why: x.why,
          source: src,
          shown: visible.slice(0, 12).map((y) => y.id),
        },
      },
      { onSuccess: (r) => done(t("done.changed", { n: i + 1 }), r), onError: fail },
    );
  };
  const tryPut = (x: Candidate) => (x.sensitive && confirm !== x.id ? setConfirm(x.id) : put(x));
  const fromLink = (text: string) => {
    const id = immichIdFrom(text);
    if (!id || !/https?:\/\//.test(text)) return false;
    put({ id, why: ["🔗 chosen in Immich"] }, "immich"); // a stored «why» chip: the server translates it
    return true;
  };
  const onPaste = (e: ClipboardEvent) => {
    const text = e.clipboardData.getData("text");
    if (fromLink(text)) e.preventDefault();
  };
  const reset = () => setShown(PAGE);

  const title =
    source === "search"
      ? t("results.search", { query })
      : source === "partners"
        ? t("results.partners")
        : all
          ? t("results.all")
          : t("results.fit");
  const count =
    items.length >= 3000
      ? t("results.capped", { n: items.length, max: 3000 })
      : t("results.count", { count: items.length });
  const sub =
    source === "partners"
      ? t("results.count", { count: items.length })
      : [
          source === "search" ? (days === "any" ? daysLabel("any") : t("days.project")) : daysLabel(days),
          people.length ? people.join(", ") : t("people.everyoneLower"),
          count,
        ].join(" · ");
  const addable = (allPeople ?? []).filter((x) => !people.includes(x.name)).sort((a, b) => b.used - a.used);

  const side = (
    <aside ref={sideRef} className={`side ${filtersOpen ? "open" : ""}`} aria-label={t("filters")}>
      {mode === "change" && (
        <>
          <div>
            <h3 data-filter="days">{t("days.label")}</h3>
            <div role="radiogroup" aria-label={t("days.label")}>
              {DAYS.filter((d) => d.id !== "album" || p.album_id).map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="opt"
                  role="radio"
                  aria-checked={days === d.id}
                  onClick={() => (setDays(d.id), reset())}
                >
                  <span className="radio" />
                  {daysLabel(d.id)}
                  {daysHint(d.id) && <span className="hint">{daysHint(d.id)}</span>}
                </button>
              ))}
            </div>
          </div>
          <div>
            <h3 data-filter="people">{t("people.label")}</h3>
            <div className="row wrap" style={{ gap: 6 }}>
              {people.map((n) => (
                <button
                  key={n}
                  type="button"
                  className="chip on"
                  aria-label={t("people.remove", { name: n })}
                  onClick={() => (setPeople(people.filter((x) => x !== n)), reset())}
                >
                  {n} <X className="ico ico-sm x" aria-hidden />
                </button>
              ))}
              <label className="chip" style={{ position: "relative" }}>
                <Plus className="ico ico-sm" aria-hidden />
                {t("people.add")}
                <select
                  aria-label={t("people.addPerson")}
                  value=""
                  onChange={(e) => e.target.value && (setPeople([...people, e.target.value]), reset())}
                  style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}
                >
                  <option value="">{t("people.addPlaceholder")}</option>
                  {addable.map((x) => (
                    <option key={x.name} value={x.name}>
                      {x.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-caption muted" style={{ margin: "8px 0 0" }}>
              {people.length ? t("people.any") : t("people.none")}
            </p>
          </div>
        </>
      )}
      <div>
        <h3 data-filter="sort">{t("sort.label")}</h3>
        <div role="radiogroup" aria-label={t("sort.label")}>
          {(
            [
              ...(source === "search" ? (["query"] as Sort[]) : []),
              ...(mode === "change" ? (["fit"] as Sort[]) : []),
              "quality",
              ...(mode === "change" ? (["near"] as Sort[]) : []),
              "new",
              "old",
            ] as Sort[]
          ).map((k) => (
            <button
              key={k}
              type="button"
              className="opt"
              role="radio"
              aria-checked={effSort === k}
              onClick={() => (setSort(k), reset())}
            >
              <span className="radio" />
              {sortName(k)}
            </button>
          ))}
        </div>
      </div>
      <div>
        <h3 data-filter="show">{t("show.label")}</h3>
        <Toggle
          label={t("show.hideUsed")}
          on={show.hideUsed}
          set={(v) => setShow({ ...show, hideUsed: v })}
        />
        <Toggle
          label={
            <Trans
              t={t}
              i18nKey="show.hideSensitive"
              components={{ icon: <TriangleAlert className="ico ico-sm warn-text" aria-hidden /> }}
            />
          }
          on={show.hideSensitive}
          set={(v) => setShow({ ...show, hideSensitive: v })}
        />
        <Toggle
          label={
            <Trans
              t={t}
              i18nKey="show.onlyFav"
              components={{ icon: <Star className="ico ico-sm" aria-hidden /> }}
            />
          }
          on={show.onlyFav}
          set={(v) => setShow({ ...show, onlyFav: v })}
        />
        <Seg
          label={t("show.shape")}
          value={show.shape}
          options={[
            ["all", t("show.shapeAll")],
            ["portrait", t("show.portrait")],
            ["landscape", t("show.landscape")],
          ]}
          set={(v) => setShow({ ...show, shape: v })}
        />
        <Seg
          label={t("show.type")}
          value={show.type}
          options={[
            ["all", t("show.typeAll")],
            ["photo", t("show.photos")],
            ["video", t("show.videos")],
          ]}
          set={(v) => setShow({ ...show, type: v })}
        />
      </div>
      {mode === "change" && (
        <div>
          <h3>{t("howMany.label")}</h3>
          <Seg
            label={t("howMany.label")}
            value={all ? "all" : "fit"}
            options={[
              ["fit", t("howMany.fit")],
              ["all", t("howMany.all")],
            ]}
            set={(v) => {
              setAll(v === "all");
              setQuery("");
              if (v === "all" && sort === "fit") setSort("near");
              if (v === "fit" && sort === "near") setSort("fit");
              reset();
            }}
          />
          <p className="text-caption muted" style={{ margin: "8px 0 0" }}>
            {t("howMany.hint")}
          </p>
        </div>
      )}
      <button
        type="button"
        className="btn primary only-mobile see-photos"
        onClick={() => setFiltersOpen(false)}
      >
        {t("seePhotos")}
      </button>
    </aside>
  );

  return (
    // pasting an Immich link anywhere in the chooser puts that photo
    <div style={{ display: "contents" }} onPaste={onPaste}>
      {side}
      <section className="main">
        <form
          className="search-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (fromLink(q)) return;
            setQuery(q.trim());
            setAll(false);
            reset();
          }}
        >
          <label className="input-ico">
            <Search className="ico" aria-hidden />
            <span className="sr-only">{t("search.label")}</span>
            <input
              data-autofocus={fine ? "" : undefined}
              className="input"
              type="search"
              placeholder={mode === "pair" ? t("search.placeholderPair") : t("search.placeholder")}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                if (!e.target.value) setQuery("");
              }}
            />
          </label>
          {config?.immich_web && (
            <a className="btn ghost hide-mobile" href={config.immich_web} target="_blank" rel="noreferrer">
              <ExternalLink className="ico ico-sm" aria-hidden />
              {t("search.openImmich")}
            </a>
          )}
        </form>

        <div className="chipbar" role="toolbar" aria-label={t("filters")}>
          {mode === "change" && (
            <>
              <button type="button" className="chip" onClick={() => openFilter("days")}>
                <Calendar className="ico ico-sm" aria-hidden />
                {daysLabel(days)}
                <ChevronDown className="ico ico-sm" aria-hidden />
              </button>
              <button type="button" className="chip" onClick={() => openFilter("people")}>
                <Users className="ico ico-sm" aria-hidden />
                {people.length ? people.join(", ") : t("people.everyone")}
                <ChevronDown className="ico ico-sm" aria-hidden />
              </button>
            </>
          )}
          <button type="button" className="chip" onClick={() => openFilter("sort")}>
            <ArrowUpDown className="ico ico-sm" aria-hidden />
            {sortName(effSort)}
            <ChevronDown className="ico ico-sm" aria-hidden />
          </button>
          <button
            type="button"
            className={`chip ${activeFilters(show) ? "on" : ""}`}
            onClick={() => openFilter("show")}
          >
            <ListFilter className="ico ico-sm" aria-hidden />
            {t("filters")}
            {activeFilters(show) ? ` · ${activeFilters(show)}` : ""}
          </button>
        </div>

        {mode === "change" ? (
          <BurstNow project={p} i={i} onPick={(id) => put({ id }, "burst")} />
        ) : (
          <div className="row">
            <button
              type="button"
              className="btn"
              onClick={() =>
                act.pair.mutate(
                  { i, asset: null },
                  {
                    onSuccess: (r) => done(t("done.auto", { n: i + 1 }), r),
                    onError: fail,
                  },
                )
              }
            >
              <Sparkles className="ico ico-sm" aria-hidden /> {t("autoPick")}
            </button>
          </div>
        )}

        <div className="res-h">
          <h3>{title}</h3>
          <span className="muted text-small">{sub}</span>
          <span className="spacer" />
          {hidden > 0 && (
            <button
              type="button"
              className="btn xs ghost"
              onClick={() => setShow({ ...DEFAULT_SHOW, hideUsed: false })}
            >
              {t("results.hidden", { count: hidden })}
            </button>
          )}
        </div>

        {current.isPending && current.fetchStatus !== "idle" ? (
          <p className="muted">
            {source === "search" ? t("loading.search") : all ? t("loading.all") : t("loading.fit")}
          </p>
        ) : current.error ? (
          <p className="danger-text">{current.error.message}</p>
        ) : !visible.length ? (
          <p className="muted">{items.length ? t("empty.filtered") : t("empty.none")}</p>
        ) : (
          <div className="grid">
            {visible.slice(0, shown).map((x) => (
              <PickCard
                key={x.id}
                x={x}
                usedIn={usedAt.get(x.id)}
                video={x.video || p.assets[x.id]?.video}
                confirming={confirm === x.id}
                onPut={() => tryPut(x)}
                onCancel={() => setConfirm(null)}
                onInfo={onInfo && (() => onInfo(x.id, i))}
              />
            ))}
          </div>
        )}
        {visible.length > shown && (
          <button type="button" className="btn more" onClick={() => setShown(shown + PAGE)}>
            {t("results.more")} <span className="muted">({visible.length - shown})</span>
          </button>
        )}
      </section>
    </div>
  );
}

function PickCard({
  x,
  usedIn,
  video,
  confirming,
  onPut,
  onCancel,
  onInfo,
}: {
  x: Candidate;
  usedIn: number | undefined;
  video?: boolean;
  confirming: boolean;
  onPut: () => void;
  onCancel: () => void;
  onInfo?: () => void;
}) {
  const { t } = useTranslation("chooser");
  const why = x.why ?? [];
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        className="pick"
        aria-label={
          x.sensitive
            ? t("card.putWarned", { date: fmtDay(x.date), warning: x.sensitive })
            : t("card.put", { date: fmtDay(x.date) })
        }
        onClick={onPut}
      >
        <div className="photo frame-43" style={{ backgroundImage: `url(${assetUrl(x.id)})` }}>
          <span className="d">{fmtDay(x.date)}</span>
          <span className="fls">
            {x.sensitive && (
              <span className="fl warn" title={x.sensitive}>
                <TriangleAlert className="ico" aria-hidden />
              </span>
            )}
            {video && (
              <span className="fl">
                <Film className="ico" aria-hidden />
              </span>
            )}
            {x.fav && (
              <span className="fl star" title={t("card.favorite")}>
                <Star className="ico" aria-hidden />
              </span>
            )}
          </span>
          {usedIn != null && <span className="used ptag">{t("card.usedIn", { n: usedIn + 1 })}</span>}
          <span className="put btn sm primary">{t("card.use")}</span>
        </div>
        {why.length > 0 && (
          <div className="why">
            {why.slice(0, 2).map((w) => (
              <span key={w} className={`chip sm ${isQualityWarning(w) ? "warn" : ""}`}>
                {w}
              </span>
            ))}
            {why.length > 2 && (
              <span className="chip sm" title={why.slice(2).join(" · ")}>
                +{why.length - 2}
              </span>
            )}
          </div>
        )}
      </button>
      {onInfo && (
        <button
          type="button"
          className="icon-btn overlay sm"
          onClick={onInfo}
          aria-label={t("card.detailsOf", { date: fmtDay(x.date) })}
          title={t("card.details")}
          style={{ position: "absolute", right: 6, top: "calc(75% - 38px)", zIndex: 3 }}
        >
          <Info className="ico ico-sm" />
        </button>
      )}
      {confirming && (
        <div className="confirm" role="alertdialog" aria-label={t("card.confirm.label")}>
          <b>
            <TriangleAlert className="ico ico-sm" aria-hidden />{" "}
            {t("card.confirm.warning", { warning: x.sensitive })}
          </b>
          <span>{t("card.confirm.ask")}</span>
          <div className="row">
            <button type="button" className="btn sm light" onClick={onPut} autoFocus>
              {t("card.confirm.yes")}
            </button>
            <button type="button" className="btn sm clear" onClick={onCancel}>
              {t("card.confirm.no")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The photo in the shot now and the other photos of that moment (the most frequent fix). */
function BurstNow({ project: p, i, onPick }: { project: Project; i: number; onPick: (id: string) => void }) {
  const { t } = useTranslation("chooser");
  const s = p.slots[i]!;
  const known = (s.burst?.length ?? 0) > 1;
  const { data } = useBurst(p.id, i, s.asset, known);
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = strip.current?.querySelector<HTMLElement>(".b.cur");
    if (el && strip.current)
      strip.current.scrollLeft = el.offsetLeft - strip.current.clientWidth / 2 + el.clientWidth / 2;
  }, [data, s.asset]);
  if (!s.asset) return null;
  return (
    <div className="now">
      <div className="curbox">
        <div className="photo frame-43 cur" style={{ backgroundImage: `url(${assetUrl(s.asset)})` }} />
        <div className="cap">{t("burst.now")}</div>
      </div>
      {known && data && data.length > 1 ? (
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ marginBottom: 6 }}>
            <Film className="ico ico-sm muted" aria-hidden />
            <span className="strong text-small">{t("burst.title", { count: data.length })}</span>
            <span className="muted text-caption hide-mobile">{t("burst.hint")}</span>
          </div>
          <div className="strip" ref={strip}>
            {data.map((b, k) => {
              const cur = b.id === s.asset;
              const q = b.why.find((w) => /^(😑|💨|〰️)/.test(w))?.slice(0, 2);
              return (
                <button
                  key={b.id}
                  type="button"
                  className={`b ${cur ? "cur" : ""}`}
                  aria-label={[
                    t("burst.photo", { n: k + 1 }),
                    ...(cur ? [t("burst.isSet")] : []),
                    ...(b.best ? [t("burst.isBest")] : []),
                  ].join(", ")}
                  onClick={() => !cur && onPick(b.id)}
                  title={b.why.join(" · ")}
                >
                  <div className="photo frame-43" style={{ backgroundImage: `url(${assetUrl(b.id)})` }} />
                  {cur ? (
                    <span className="tag">{t("burst.set")}</span>
                  ) : b.best ? (
                    <span className="tag best">{t("burst.best")}</span>
                  ) : null}
                  {q && <span className="q">{q}</span>}
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <div />
      )}
    </div>
  );
}

function Toggle({ label, on, set }: { label: React.ReactNode; on: boolean; set: (v: boolean) => void }) {
  return (
    <label className="tog">
      <span>{label}</span>
      <button type="button" className="switch" role="switch" aria-checked={on} onClick={() => set(!on)} />
    </label>
  );
}

function Seg<T extends string>({
  label,
  value,
  options,
  set,
}: {
  label: string;
  value: T;
  options: [T, string][];
  set: (v: T) => void;
}) {
  return (
    <div className="seg stretch" role="group" aria-label={label} style={{ marginTop: 8 }}>
      {options.map(([v, t]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => set(v)}>
          {t}
        </button>
      ))}
    </div>
  );
}

/** Immich people named in a lyric line, as whole words with a capital letter («With Nico and Lía»). */
export function namedIn(lyric: string | undefined, people: { name: string }[]): string[] {
  if (!lyric) return [];
  return people
    .map((x) => x.name)
    .filter(
      (n) =>
        n.length >= 3 &&
        new RegExp(`(^|[^\\p{L}])${n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^\\p{L}])`, "u").test(lyric),
    );
}
