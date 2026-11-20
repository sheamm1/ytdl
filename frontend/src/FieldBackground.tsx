import { useEffect, useRef, useState } from "react";

/**
 * YOUFETCH background: a field of floating "video cards" representing
 * different fields of profession. Each card drifts randomly (CSS animation).
 *
 * INTERACTION: when the cursor approaches a card, that card JUMPS — it gets
 * pushed away and bounces back (springy repel) via a JS-driven transform on
 * an outer wrapper (so it doesn't fight the CSS drift on the inner card).
 *
 * When `activity` > 0 (a download is running) the cards speed up.
 */

type Card = {
  id: number;
  icon: string;
  label: string;
  x: number; // % left
  y: number; // % top
  size: number; // px
  dur: number; // s
  delay: number; // s
  rot: number; // deg
};

const FIELDS: { icon: string; label: string }[] = [
  { icon: "🎬", label: "Cinema" },
  { icon: "🎮", label: "Gaming" },
  { icon: "🍳", label: "Cooking" },
  { icon: "💪", label: "Fitness" },
  { icon: "🎵", label: "Music" },
  { icon: "💻", label: "Tech" },
  { icon: "✈️", label: "Travel" },
  { icon: "📚", label: "Education" },
  { icon: "⚽", label: "Sports" },
  { icon: "🔬", label: "Science" },
  { icon: "👗", label: "Fashion" },
  { icon: "🍜", label: "Food" },
  { icon: "🎓", label: "Lectures" },
  { icon: "🏀", label: "Basketball" },
  { icon: "🎹", label: "Piano" },
  { icon: "🧘", label: "Yoga" },
  { icon: "🚀", label: "Space" },
  { icon: "🎤", label: "Podcast" },
  { icon: "🏔️", label: "Hiking" },
  { icon: "📷", label: "Photography" },
];

function makeCards(count: number): Card[] {
  return Array.from({ length: count }, (_, i) => {
    const f = FIELDS[i % FIELDS.length];
    return {
      id: i,
      icon: f.icon,
      label: f.label,
      x: Math.random() * 90 + 3,
      y: Math.random() * 85 + 5,
      size: 54 + Math.random() * 40,
      dur: 18 + Math.random() * 22,
      delay: -Math.random() * 30,
      rot: (Math.random() - 0.5) * 24,
    };
  });
}

function cardCount() {
  const w = typeof window !== "undefined" ? window.innerWidth : 1024;
  if (w <= 480) return 10;   // phone: fewer, less busy
  if (w <= 768) return 15;   // tablet
  return 22;                 // desktop
}

export default function FieldBackground({ activity }: { activity: number }) {
  const [cards, setCards] = useState<Card[]>(() => makeCards(cardCount()));
  const wrapRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const activityRef = useRef(activity);
  activityRef.current = activity;

  // regenerate on resize (viewport-dependent count)
  useEffect(() => {
    const onResize = () => setCards(makeCards(cardCount()));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // speed up cards during activity
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    el.style.setProperty("--speed", activity > 0 ? "0.35" : "1");
  }, [activity]);

  // ---- cursor repel / jump interaction ----
  useEffect(() => {
    const RADIUS = 130;        // px influence radius
    const MAX_PUSH = 46;       // px max displacement
    const SPRING = 0.12;       // lerp factor (lower = floatier)
    let mx = -9999, my = -9999;
    const onMove = (e: MouseEvent) => { mx = e.clientX; my = e.clientY; };
    window.addEventListener("mousemove", onMove);

    // per-card spring state
    const state = new Map<number, { ox: number; oy: number; tx: number; ty: number; s: number }>();
    let raf = 0;

    const loop = () => {
      raf = requestAnimationFrame(loop);
      const cards = cardRefs.current;
      for (let i = 0; i < cards.length; i++) {
        const el = cards[i];
        if (!el) continue;
        let st = state.get(i);
        if (!st) { st = { ox: 0, oy: 0, tx: 0, ty: 0, s: 1 }; state.set(i, st); }

        const r = el.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        const dx = cx - mx;
        const dy = cy - my;
        const dist = Math.hypot(dx, dy);

        if (dist < RADIUS) {
          const force = (1 - dist / RADIUS);           // 0..1
          const push = force * MAX_PUSH;
          const inv = dist === 0 ? 0 : 1 / dist;
          st.tx = dx * inv * push;
          st.ty = dy * inv * push;
          st.s = 1 + force * 0.25;                     // slight scale-up (jump)
        } else {
          st.tx = 0; st.ty = 0; st.s = 1;
        }

        st.ox += (st.tx - st.ox) * SPRING;
        st.oy += (st.ty - st.oy) * SPRING;
        st.s += (st.s - st.s) * 0 + (st.s === 1 ? 0 : (1 - st.s) * SPRING);
        // smooth scale toward target 1
        const targetS = (dist < RADIUS) ? 1 + (1 - dist / RADIUS) * 0.25 : 1;
        st.s += (targetS - st.s) * SPRING;

        el.style.transform = `translate(${st.ox}px, ${st.oy}px) scale(${st.s})`;
      }
    };
    raf = requestAnimationFrame(loop);
    return () => { window.removeEventListener("mousemove", onMove); cancelAnimationFrame(raf); };
  }, []);

  return (
    <div ref={wrapRef} className="field-bg" aria-hidden="true">
      {/* vintage objects lying on the archive "table" — periphery only,
          so the central card + text always stay readable */}
      <div className="table-objects">
        <span className="tobj tobj-book1">📕</span>
        <span className="tobj tobj-book2">📗</span>
        <span className="tobj tobj-book3">📙</span>
        <span className="tobj tobj-mag">🔍</span>
        <span className="tobj tobj-quill">🪶</span>
        <span className="tobj tobj-env">✉️</span>
        <span className="tobj tobj-stamp">📮</span>
        <span className="tobj tobj-map">🗺️</span>
        <span className="tobj tobj-lens">🧿</span>
        <span className="tobj tobj-key">🗝️</span>
      </div>
      {cards.map((c, i) => (
        <div
          key={c.id}
          ref={(el) => { cardRefs.current[i] = el; }}
          className="field-card-magnet"
          style={{ left: `${c.x}%`, top: `${c.y}%` }}
        >
          <div
            className="field-card"
            style={{
              width: c.size,
              height: c.size,
              animationDuration: `${c.dur}s`,
              animationDelay: `${c.delay}s`,
              ["--rot" as string]: `${c.rot}deg`,
            }}
          >
            <span className="field-card__icon">{c.icon}</span>
            <span className="field-card__label">{c.label}</span>
            <span className="field-card__play">▶</span>
          </div>
        </div>
      ))}
    </div>
  );
}
