import { useCallback, useEffect, useRef, useState } from "react";
import FieldBackground from "./FieldBackground";
import { fetchUsage, getJob, igConnect, igStatus, submitJob } from "./api";
import {
  AUDIO_FORMATS,
  QUALITY_OPTIONS,
  TIER_LABEL,
  TIER_PRICE,
  qualityAllowed,
  type JobState,
  type Tier,
  type Usage,
} from "./types";

type Phase = "idle" | "submitting" | "working" | "done" | "error";
const ALL_TIERS: Tier[] = ["free", "plus", "power"];

/* ---- preloader ---- */
function Preloader({ onDone }: { onDone: () => void }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      i += Math.floor(Math.random() * 12) + 3;
      if (i >= 100) {
        i = 100;
        clearInterval(id);
        setTimeout(onDone, 400);
      }
      setN(i);
    }, 60);
    return () => clearInterval(id);
  }, [onDone]);

  return (
    <div className={`preloader ${n >= 100 ? "preloader--done" : ""}`}>
      <div className="preloader__num">{n}</div>
      <div className="preloader__bar">
        <div className="preloader__fill" style={{ width: `${n}%` }} />
      </div>
      <div className="preloader__label">initializing</div>
    </div>
  );
}

/* ---- vintage pen cursor: now a native CSS cursor (zero-lag), see styles.css ---- */

/* ---- 3D tilt + magnetic ---- */
function useTilt(maxDeg = 5) {
  const ref = useRef<HTMLDivElement>(null);
  const onMove = useCallback((e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(900px) rotateY(${x * maxDeg}deg) rotateX(${-y * maxDeg}deg) translateZ(0)`;
  }, [maxDeg]);
  const onLeave = useCallback(() => {
    if (ref.current)
      ref.current.style.transform = "perspective(900px) rotateY(0deg) rotateX(0deg)";
  }, []);
  return { ref, onMove, onLeave };
}

function MagneticButton({ children, onClick, disabled, className }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean; className?: string;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const onMove = (e: React.MouseEvent) => {
    const el = ref.current;
    if (!el || disabled) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left - r.width / 2) / r.width;
    const y = (e.clientY - r.top - r.height / 2) / r.height;
    el.style.transform = `translate(${x * 8}px, ${y * 6}px)`;
  };
  const onLeave = () => {
    if (ref.current) ref.current.style.transform = "translate(0,0)";
  };
  return (
    <button
      ref={ref}
      className={`cta cta--magnetic ${className ?? ""}`}
      onClick={onClick}
      disabled={disabled}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
    >
      {children}
    </button>
  );
}

/* ---- main app ---- */
export default function App() {
  const [loaded, setLoaded] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const tilt = useTilt(5);

  const [url, setUrl] = useState("");
  const [quality, setQuality] = useState("480");
  const [audioOnly, setAudioOnly] = useState(false);
  const [audioFormat, setAudioFormat] = useState("mp3");

  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<JobState | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [submitError, setSubmitError] = useState("");

  const [usage, setUsage] = useState<Usage | null>(null);
  const [showUpgrade, setShowUpgrade] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Instagram connect (per-user cookies)
  const [igConnected, setIgConnected] = useState(false);
  const [igShowForm, setIgShowForm] = useState(false);
  const [igCookies, setIgCookies] = useState("");
  const [igBusy, setIgBusy] = useState(false);
  const [igMsg, setIgMsg] = useState("");

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const loadUsage = useCallback(async () => {
    try {
      const u = await fetchUsage();
      setUsage(u);
      if (!qualityAllowed(quality, u.max_quality)) setQuality(u.max_quality);
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quality]);

  useEffect(() => { loadUsage(); }, [loadUsage]);

  // trigger text reveal after preloader
  useEffect(() => {
    if (loaded) {
      const t = setTimeout(() => setRevealed(true), 100);
      return () => clearTimeout(t);
    }
  }, [loaded]);

  const startPolling = useCallback((id: string) => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const state = await getJob(id);
        setJob(state);
        // prefer the server's real overall pct; fall back to parsing the text
        if (typeof state.pct === "number") {
          setProgressPct(state.pct);
        } else {
          const m = (state.progress || "").match(/(\d+(?:\.\d+)?)%/);
          if (m) setProgressPct(parseFloat(m[1]));
        }
        if (state.status === "done") {
          stopPolling();
          setPhase("done");
          loadUsage();
        } else if (state.status === "error") {
          stopPolling();
          setPhase("error");
        }
      } catch { /* keep polling */ }
    }, 1200);
  }, [stopPolling, loadUsage]);

  const busy = phase === "submitting" || phase === "working";
  const maxQuality = usage?.max_quality ?? "480";

  // Is the pasted URL an Instagram one? (drives the connect panel)
  const isInstagram = /instagram\.com/i.test(url);

  const refreshIg = useCallback(async () => {
    try {
      const s = await igStatus();
      setIgConnected(s.connected);
      if (s.connected) setIgShowForm(false);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refreshIg(); }, [refreshIg]);

  async function handleIgConnect() {
    setIgBusy(true);
    setIgMsg("");
    try {
      const r = await igConnect(igCookies);
      setIgConnected(true);
      setIgShowForm(false);
      setIgCookies("");
      setIgMsg(r.message || "connected ✓");
      setTimeout(() => setIgMsg(""), 4000);
    } catch (err) {
      setIgMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setIgBusy(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || busy) return;
    setPhase("submitting");
    setJob(null);
    setProgressPct(0);
    setSubmitError("");
    try {
      const id = await submitJob({ url: trimmed, quality, audio_only: audioOnly, audio_format: audioFormat });
      setPhase("working");
      startPolling(id);
    } catch (err) {
      setPhase("error");
      const msg = err instanceof Error ? err.message : String(err);
      setSubmitError(msg);
      if (/paid plan|bandwidth used up/i.test(msg)) setShowUpgrade(true);
      setJob({ id: "", status: "error", progress: "", title: "", error: msg });
    }
  }

  const statusText =
    phase === "submitting" ? "submitting…" :
    phase === "working" ? job?.progress || "working…" : "";

  if (!loaded) return <Preloader onDone={() => setLoaded(true)} />;

  const rv = (cls: string) => `${cls} reveal ${revealed ? "reveal--visible" : ""}`;
  const activity = busy ? 1 : 0;

  return (
    <>
      <FieldBackground activity={activity} />
      <div className="shell" ref={tilt.ref} onMouseMove={tilt.onMove} onMouseLeave={tilt.onLeave}>

        <div className={rv("masthead")}>
          <div className="masthead__logo">
            <span className="dot" />
            <span className="brand-word">YOU<span className="brand-accent">FETCH</span></span>
          </div>
          <h1 className="masthead__title">
            Paste a link.<br />
            Get the <em>file</em>.
          </h1>
          <p className="masthead__sub">
            Highest-quality downloads from YouTube, Instagram &amp; X. No install, no friction.
          </p>
        </div>

        {/* bandwidth usage hidden from view (still enforced server-side) */}

        <form onSubmit={handleSubmit} className={rv("")}>
          <div className="field">
            <label className="field__label" htmlFor="url">url</label>
            <input
              id="url"
              className="field__input"
              type="url"
              placeholder="YouTube, Instagram, or X video link…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy}
              autoComplete="off"
            />
          </div>

          {isInstagram && (
            <div className="ig-connect">
              {igConnected ? (
                <div className="ig-connect__ok">instagram connected ✓</div>
              ) : igShowForm ? (
                <>
                  <div className="ig-connect__title">connect instagram</div>
                  <p className="ig-connect__hint">
                    Instagram needs your login. Install a "Get cookies.txt"
                    browser extension, log into instagram.com, export your
                    cookies, and paste them here.
                  </p>
                  <textarea
                    className="ig-connect__input"
                    rows={4}
                    placeholder={"# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\t...\t..."}
                    value={igCookies}
                    onChange={(e) => setIgCookies(e.target.value)}
                    disabled={igBusy}
                  />
                  {igMsg && <div className="ig-connect__msg">{igMsg}</div>}
                  <div className="ig-connect__row">
                    <button className="link-btn" onClick={handleIgConnect} disabled={igBusy || igCookies.trim().length < 20}>
                      {igBusy ? "checking…" : "connect"}
                    </button>
                    <button className="link-btn" onClick={() => setIgShowForm(false)}>cancel</button>
                  </div>
                </>
              ) : (
                <button className="ig-connect__link" onClick={() => setIgShowForm(true)}>
                  instagram needs login — connect →
                </button>
              )}
            </div>
          )}

          <div className="field__row">
            <div className="field">
              <label className="field__label" htmlFor="quality">quality</label>
              <select
                id="quality"
                className="field__select"
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                disabled={busy}
              >
                {QUALITY_OPTIONS.map((o) => {
                  const allowed = qualityAllowed(o.value, maxQuality);
                  return (
                    <option key={o.value} value={o.value} disabled={!allowed}>
                      {o.label}{!allowed ? " (paid)" : ""}
                    </option>
                  );
                })}
              </select>
            </div>
            {audioOnly && (
              <div className="field">
                <label className="field__label" htmlFor="afmt">format</label>
                <select
                  id="afmt"
                  className="field__select"
                  value={audioFormat}
                  onChange={(e) => setAudioFormat(e.target.value)}
                  disabled={busy}
                >
                  {AUDIO_FORMATS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <label className="toggle">
            <input
              type="checkbox"
              checked={audioOnly}
              onChange={(e) => setAudioOnly(e.target.checked)}
              disabled={busy}
            />
            audio only
          </label>

          <MagneticButton disabled={!url.trim() || busy}>
            {busy ? "working…" : "get file ↓"}
          </MagneticButton>
        </form>

        {busy && (
          <>
            <div className="progress">
              <div className="progress__fill" style={{ width: `${progressPct}%` }} />
            </div>
            <div className="status status--muted work-status">
              {job?.progress || statusText || "starting…"}
              {progressPct > 0 && <span className="work-pct"> {progressPct}%</span>}
            </div>
          </>
        )}

        {phase === "done" && job?.download && (
          <>
            <div className="status status--ok">ready ✓</div>
            <a className="dl-btn" href={job.download} download>
              ↓ download {job.title || "file"}
            </a>
          </>
        )}

        {phase === "error" && (
          <div className="status status--err">
            {submitError || job?.error || "error"}
          </div>
        )}

        {showUpgrade && (
          <div className="upgrade">
            <div className="upgrade__title">Upgrade</div>
            <p className="upgrade__sub">Unlock 720p–4K and more bandwidth.</p>
            <div className="plans">
              {ALL_TIERS.filter((t) => t !== "free").map((t) => (
                <a
                  key={t}
                  className="plan"
                  href={`mailto:upgrade@ytdl.app?subject=Upgrade to ${TIER_LABEL[t]}&body=Hi,%0D%0AI%20d%20like%20to%20upgrade%20to%20the%20${TIER_LABEL[t]}%20plan.`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="plan__name">{TIER_LABEL[t]}</span>
                  <span className="plan__price">{TIER_PRICE[t]}</span>
                  <span className="plan__detail">
                    {t === "plus" ? "1080p · 50 GB/mo" : "4K · 300 GB/mo"}
                  </span>
                  <span className="plan__cta">contact →</span>
                </a>
              ))}
            </div>
            <button className="link-btn" onClick={() => setShowUpgrade(false)}>
              dismiss
            </button>
          </div>
        )}

        <div className={rv("foot")}>
          <span>no sign-up · 24h expiry</span>
          {usage && usage.tier === "free" && (
            <button onClick={() => setShowUpgrade(true)}>upgrade</button>
          )}
        </div>

      </div>
    </>
  );
}
