import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { useDemoMode } from "@/hooks/useDemoMode";
import { useDemoTour } from "@/stores/demoTour";

interface Step {
  anchor: string;
  route: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    anchor: "email-origin",
    route: "/",
    title: "Emailed bank notifications",
    body: "Every transaction here came from a bank email forwarded to your own Gmail. Click the mail icon on any row to see the source.",
  },
  {
    anchor: "category-pill",
    route: "/",
    title: "Categories you can override",
    body: "An LLM assigns categories using your rules. When it gets one wrong, click the pill to reassign — the override sticks.",
  },
  {
    anchor: "comment-action",
    route: "/",
    title: "Notes, not just numbers",
    body: "Add notes to spending. This is a journal, not a ledger.",
  },
  {
    anchor: "insights-nav",
    route: "/",
    title: "Monthly AI briefings",
    body: "Anomalies, category deep dives, budget pace. Pick a past month to read one.",
  },
  {
    anchor: "self-host-cta",
    route: "/",
    title: "Your data, your machine",
    body: "Everything you see runs locally when self-hosted. About five minutes to set up — here's the guide.",
  },
];

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

// Clearance around the anchor element; the spotlight ring sits just outside
// this padding and the step card is positioned beyond that.
const RING_PADDING = 6;
const CARD_GAP = 12;
const CARD_WIDTH = 320;
// Max rAF ticks to wait for an anchor after a step activates (~600ms @ 60fps).
// If the anchor still isn't in the DOM after this window, we give up and close.
const ANCHOR_RETRY_FRAMES = 40;

function readAnchorRect(selector: string): Rect | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${selector}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function DemoTour() {
  const demo = useDemoMode();
  const isOpen = useDemoTour((s) => s.isOpen);
  const step = useDemoTour((s) => s.step);
  const close = useDemoTour((s) => s.close);
  const next = useDemoTour((s) => s.next);
  const back = useDemoTour((s) => s.back);
  const setTotalSteps = useDemoTour((s) => s.setTotalSteps);

  const navigate = useNavigate();
  const location = useLocation();

  const [rect, setRect] = useState<Rect | null>(null);
  const [vw, setVw] = useState(() => (typeof window === "undefined" ? 0 : window.innerWidth));
  const [vh, setVh] = useState(() => (typeof window === "undefined" ? 0 : window.innerHeight));
  const reducedMotion = prefersReducedMotion();
  const cardRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // True while we're waiting for our own navigate() call to land; lets the
  // pathname-watch effect distinguish tour-driven navigation from the user
  // clicking away in the sidebar.
  const expectingNav = useRef(false);
  // Step index we've already scrolled into view — prevents re-scrolling on
  // every re-measure while keeping per-step scroll-on-activate behavior.
  const scrolledForStep = useRef<number | null>(null);

  useEffect(() => {
    setTotalSteps(STEPS.length);
  }, [setTotalSteps]);

  // While the tour is open, mark the document so anchors that are hidden at
  // rest can force themselves visible under the spotlight — chiefly the row's
  // hover-reveal action cluster, where step 1's mail icon lives (it's
  // opacity-0 until hover). See the `[.tour-active_&]` rule in
  // JournalTransactionRow. useLayoutEffect so the class lands before paint.
  useLayoutEffect(() => {
    if (!isOpen) return;
    const root = document.documentElement;
    root.classList.add("tour-active");
    return () => root.classList.remove("tour-active");
  }, [isOpen]);

  // When the tour opens or advances to a step with a different route, navigate
  // there. Clearing the rect avoids a flash of the old step's ring on the new
  // page before the new anchor resolves.
  useEffect(() => {
    if (!isOpen) return;
    const target = STEPS[step]?.route;
    if (!target) return;
    if (location.pathname !== target) {
      expectingNav.current = true;
      setRect(null);
      navigate(target);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, step]);

  // Watch the pathname. If it leaves the current step's route without us
  // initiating the move, the user navigated manually — close quietly.
  useEffect(() => {
    if (!isOpen) return;
    const target = STEPS[step]?.route;
    if (location.pathname === target) {
      expectingNav.current = false;
      return;
    }
    if (expectingNav.current) return;
    close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  // Reset internal state when the tour closes so a later reopen starts fresh.
  useEffect(() => {
    if (!isOpen) {
      setRect(null);
      scrolledForStep.current = null;
      expectingNav.current = false;
    }
  }, [isOpen]);

  // Locate the step's anchor (with a short rAF poll), scroll it into view once
  // per step, and keep the rect in sync with layout changes afterwards.
  useLayoutEffect(() => {
    if (!isOpen) return;
    const target = STEPS[step]?.route;
    if (location.pathname !== target) return;

    let cancelled = false;
    let rafId: number | null = null;
    let attempts = 0;

    const currentStep = STEPS[step];
    if (!currentStep) return;
    const anchorSelector = currentStep.anchor;

    const poll = () => {
      if (cancelled) return;
      const el = document.querySelector<HTMLElement>(`[data-tour="${anchorSelector}"]`);
      const r = el ? el.getBoundingClientRect() : null;
      if (!el || !r || (r.width === 0 && r.height === 0)) {
        attempts++;
        if (attempts >= ANCHOR_RETRY_FRAMES) {
          // The anchor never resolved (a route where it isn't rendered, or a
          // viewport that hides it — e.g. the sidebar on mobile). Degrade
          // gracefully: skip to the next step rather than tearing the whole
          // tour down. Only reaching the end or an explicit user close ends
          // the tour (and persists "dismissed").
          if (step < STEPS.length - 1) next();
          else close();
          return;
        }
        rafId = requestAnimationFrame(poll);
        return;
      }
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      setVw(window.innerWidth);
      setVh(window.innerHeight);
      if (scrolledForStep.current !== step) {
        scrolledForStep.current = step;
        try {
          el.scrollIntoView({
            block: "center",
            inline: "center",
            behavior: reducedMotion ? "auto" : "smooth",
          });
        } catch {
          el.scrollIntoView();
        }
      }
    };

    rafId = requestAnimationFrame(poll);

    const onLayoutChange = () => {
      const r = readAnchorRect(anchorSelector);
      if (r) setRect(r);
      setVw(window.innerWidth);
      setVh(window.innerHeight);
    };
    window.addEventListener("scroll", onLayoutChange, true);
    window.addEventListener("resize", onLayoutChange);
    const ro = new ResizeObserver(onLayoutChange);
    ro.observe(document.body);

    return () => {
      cancelled = true;
      if (rafId !== null) cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", onLayoutChange, true);
      window.removeEventListener("resize", onLayoutChange);
      ro.disconnect();
    };
  }, [isOpen, step, location.pathname, reducedMotion, close, next]);

  // Keyboard: Esc closes, arrows navigate. Attached at document level so the
  // tour reacts even when focus is elsewhere.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        if (step < STEPS.length - 1) next();
        else close();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, step, next, back, close]);

  // Focus management: move focus into the card once the step is actually
  // visible (rect resolved), and restore focus when the tour closes.
  useEffect(() => {
    if (!isOpen) {
      previouslyFocused.current?.focus?.();
      previouslyFocused.current = null;
      return;
    }
    if (!rect) return;
    if (previouslyFocused.current) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const t = requestAnimationFrame(() => {
      cardRef.current?.focus();
    });
    return () => cancelAnimationFrame(t);
  }, [isOpen, rect]);

  if (!demo || !isOpen) return null;
  const current = STEPS[step];
  if (!current) return null;
  // While we're navigating or still polling for the anchor, render nothing.
  // No centered-card fallback — that was the "tour overlays the wrong page" bug.
  if (!rect || location.pathname !== current.route) return null;

  // Position the step card: prefer below, flip above if off-screen.
  const ringStyle: React.CSSProperties = {
    top: rect.top - RING_PADDING,
    left: rect.left - RING_PADDING,
    width: rect.width + RING_PADDING * 2,
    height: rect.height + RING_PADDING * 2,
  };
  const belowTop = rect.top + rect.height + CARD_GAP;
  const approxCardHeight = 180;
  const cardTop =
    belowTop + approxCardHeight > vh - 12
      ? Math.max(12, rect.top - approxCardHeight - CARD_GAP)
      : belowTop;
  const cardLeft = Math.min(Math.max(12, rect.left), vw - CARD_WIDTH - 12);

  const ringBaseClasses =
    "pointer-events-none absolute rounded-lg ring-2 ring-brand/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.04)]";
  const ringClasses = reducedMotion
    ? ringBaseClasses
    : `${ringBaseClasses} transition-all duration-200`;

  const isLast = step === STEPS.length - 1;
  const isFirst = step === 0;

  // Focus trap inside the card: capture Tab/Shift+Tab.
  const onTrapKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const root = cardRef.current;
    if (!root) return;
    const focusable = root.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  // Click-outside dismissal: wrapper catches pointerdown only when the click
  // didn't land on the card or the highlighted anchor.
  const onWrapperPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (cardRef.current?.contains(target)) return;
    const anchor = document.querySelector(`[data-tour="${current.anchor}"]`);
    if (anchor?.contains(target)) {
      close();
      return;
    }
    close();
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[60]"
      onPointerDown={onWrapperPointerDown}
      style={{ pointerEvents: "auto", background: "transparent" }}
      aria-hidden={false}
    >
      <div aria-hidden className={ringClasses} style={ringStyle} />
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- role="dialog" needs keydown for focus trap and pointerdown for stopPropagation */}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="false"
        aria-labelledby="demo-tour-title"
        tabIndex={-1}
        onKeyDown={onTrapKeyDown}
        onPointerDown={(e) => e.stopPropagation()}
        className="absolute rounded-xl border bg-card text-card-foreground shadow-xl focus:outline-none"
        style={{ top: cardTop, left: cardLeft, width: CARD_WIDTH }}
      >
        <div className="flex items-start justify-between gap-3 px-4 pt-3">
          <div>
            <div
              className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground"
              aria-live="polite"
            >
              Step {step + 1} of {STEPS.length}
            </div>
            <h3 id="demo-tour-title" className="mt-0.5 text-sm font-semibold">
              {current.title}
            </h3>
          </div>
          <button
            type="button"
            aria-label="Close tour"
            onClick={close}
            className="-mr-1 -mt-0.5 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="px-4 pt-2 text-sm text-muted-foreground leading-relaxed">{current.body}</p>
        <div className="mt-3 flex items-center justify-between border-t px-3 py-2">
          <button
            type="button"
            onClick={back}
            disabled={isFirst}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Back
          </button>
          <button
            type="button"
            onClick={() => (isLast ? close() : next())}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            {isLast ? "Done" : "Next"}
            {!isLast && <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
