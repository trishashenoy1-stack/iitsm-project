import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import type { Priority } from "../api/types";
import { PRIORITY_LABEL } from "../lib/format";
import { clock } from "../lib/sla";
import { PriorityTag } from "./IncidentBits";

interface Scenario {
  id: string;
  priority: Priority;
  title: string;
  service: string;
  reporter: string;
  technician: string;
  targetSeconds: number;
  startLeft: number;
  endLeft: number;
}

// Sample content for the animation only. Targets match SLAPolicy.default().
const SCENARIOS: Scenario[] = [
  { id: "INC1024", priority: "P1", title: "Payment application unavailable", service: "Payment", reporter: "Priya", technician: "Arjun", targetSeconds: 1800, startLeft: 900, endLeft: 180 },
  { id: "INC1031", priority: "P2", title: "VPN drops every few minutes", service: "Network", reporter: "Kabir", technician: "Dev", targetSeconds: 7200, startLeft: 6100, endLeft: 2400 },
  { id: "INC1038", priority: "P1", title: "Single sign-on rejects every user", service: "Authentication", reporter: "Ananya", technician: "Isha", targetSeconds: 1800, startLeft: 800, endLeft: 90 },
];

const STAGES = [
  { label: "Reported", ms: 1500 },
  { label: "Prioritised", ms: 1400 },
  { label: "Assigned", ms: 1500 },
  { label: "In progress", ms: 3800 },
  { label: "Resolved", ms: 3000 },
];
const EXIT_MS = 600;
const EXIT_STAGE = STAGES.length;
const STILL_FRAME_STAGE = 3;

const TOTAL_MS = STAGES.reduce((sum, s) => sum + s.ms, 0) + EXIT_MS;
const COUNTDOWN_MS = STAGES.slice(0, 4).reduce((sum, s) => sum + s.ms, 0);
const TRACK = "M 28 62 C 110 12, 170 104, 262 58 S 420 14, 502 60 S 590 84, 612 48";
const VIEW_W = 640;
const VIEW_H = 118;

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

function logLines(s: Scenario) {
  return [
    `${s.id} created by ${s.reporter}`,
    `Priority calculated as ${s.priority}`,
    `Assigned to ${s.technician} by skill-based strategy`,
    "Investigation started",
    `Marked resolved. ${s.reporter} notified.`,
  ];
}

function positionAt(elapsed: number) {
  let start = 0;
  for (let index = 0; index < STAGES.length; index++) {
    const end = start + STAGES[index].ms;
    if (elapsed < end) return { stage: index, fraction: (elapsed - start) / STAGES[index].ms };
    start = end;
  }
  return { stage: EXIT_STAGE, fraction: 1 };
}

/** Decorative: one incident at a time moves through the real lifecycle while its SLA clock runs. */
export function IncidentStory() {
  const reduceMotion = useRef(window.matchMedia("(prefers-reduced-motion: reduce)").matches).current;
  const [scenarioIndex, setScenarioIndex] = useState(0);
  const [stage, setStage] = useState(reduceMotion ? STILL_FRAME_STAGE : 0);
  const [nodes, setNodes] = useState<{ x: number; y: number }[]>([]);

  const panel = useRef<HTMLDivElement>(null);
  const tile = useRef<HTMLDivElement>(null);
  const clockText = useRef<HTMLParagraphElement>(null);
  const clockCaption = useRef<HTMLParagraphElement>(null);
  const bar = useRef<HTMLSpanElement>(null);
  const trackPath = useRef<SVGPathElement>(null);
  const trackDone = useRef<SVGPathElement>(null);
  const comet = useRef<SVGGElement>(null);

  useLayoutEffect(() => {
    const path = trackPath.current!;
    const length = path.getTotalLength();
    setNodes(
      STAGES.map((_, index) => {
        const point = path.getPointAtLength((length * index) / (STAGES.length - 1));
        return { x: point.x, y: point.y };
      }),
    );
  }, []);

  useEffect(() => {
    let scenario = 0;
    let shownStage = -1;
    let elapsed = 0;
    let last = performance.now();
    let frameId = 0;
    const path = trackPath.current!;
    const length = path.getTotalLength();

    function paint(time: number, progress: number, stopped: boolean) {
      // React clears refs before this effect's cleanup runs, so a last frame can land between them.
      if (!tile.current) return;
      const s = SCENARIOS[scenario];
      const ratio = Math.min(time / COUNTDOWN_MS, 1);
      const left = Math.round(s.startLeft + (s.endLeft - s.startLeft) * ratio);
      const warning = left / s.targetSeconds <= 0.2;
      tile.current!.dataset.state = stopped ? "done" : warning ? "warning" : "ok";
      clockText.current!.textContent = stopped ? "Stopped" : clock(left);
      clockText.current!.dataset.stopped = String(stopped);
      clockCaption.current!.textContent = stopped ? `Resolved with ${clock(s.endLeft)} to spare` : "Left to resolve";
      bar.current!.style.width = `${(100 * left) / s.targetSeconds}%`;
      trackDone.current!.style.strokeDashoffset = String(1 - progress);
      const head = path.getPointAtLength(progress * length);
      comet.current!.setAttribute("transform", `translate(${head.x} ${head.y})`);
    }

    if (reduceMotion) {
      paint(COUNTDOWN_MS * 0.9, STILL_FRAME_STAGE / (STAGES.length - 1), false);
      return;
    }

    function frame(now: number) {
      // A capped delta means a backgrounded tab resumes where it left off.
      elapsed += Math.min(now - last, 100);
      last = now;
      if (elapsed >= TOTAL_MS) {
        elapsed = 0;
        scenario = (scenario + 1) % SCENARIOS.length;
        setScenarioIndex(scenario);
      }
      const position = positionAt(elapsed);
      if (position.stage !== shownStage) {
        shownStage = position.stage;
        setStage(position.stage);
      }
      const segments = STAGES.length - 1;
      const progress =
        position.stage >= segments ? 1 : (position.stage + ease(Math.min(position.fraction * 1.6, 1))) / segments;
      paint(elapsed, progress, position.stage >= segments);
      frameId = requestAnimationFrame(frame);
    }

    frameId = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(frameId);
  }, [reduceMotion]);

  function tilt(event: PointerEvent<HTMLDivElement>) {
    if (reduceMotion || !panel.current) return;
    const box = panel.current.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width - 0.5;
    const y = (event.clientY - box.top) / box.height - 0.5;
    panel.current.style.setProperty("--tilt-x", `${(-y * 5).toFixed(2)}deg`);
    panel.current.style.setProperty("--tilt-y", `${(x * 7).toFixed(2)}deg`);
  }

  function resetTilt() {
    panel.current?.style.setProperty("--tilt-x", "0deg");
    panel.current?.style.setProperty("--tilt-y", "0deg");
  }

  const scenario = SCENARIOS[scenarioIndex];
  const lines = logLines(scenario);
  const visibleLines = lines.slice(0, Math.min(stage, STAGES.length - 1) + 1).slice(-3);
  const resolved = stage === STAGES.length - 1;

  return (
    <div ref={panel} aria-hidden="true" onPointerMove={tilt} onPointerLeave={resetTilt} className="story relative flex h-full min-h-[620px] flex-col justify-center overflow-hidden rounded-[20px] bg-panel px-[clamp(28px,5vw,72px)] py-12">
      <div className="story-aurora story-aurora-a" />
      <div className="story-aurora story-aurora-b" />

      <svg className="absolute inset-0 size-full" viewBox="0 0 800 800" preserveAspectRatio="xMidYMid slice" fill="none">
        {[
          "M -20 120 C 180 150, 240 300, 400 340",
          "M -20 420 C 120 410, 240 390, 400 380",
          "M -20 730 C 160 690, 260 500, 400 420",
          "M 820 90 C 640 150, 560 300, 400 340",
          "M 820 450 C 680 430, 560 400, 400 380",
          "M 820 720 C 640 700, 540 500, 400 420",
        ].map((d, index) => (
          <g key={d}>
            <path d={d} className="stroke-line" strokeWidth="1" />
            <path d={d} pathLength={100} className="story-flow" strokeWidth="1.4" style={{ animationDelay: `${index * -0.85}s` }} />
          </g>
        ))}
      </svg>

      <div className="relative mx-auto w-full max-w-[640px]">
        <p className="mb-7 max-w-[420px] text-[clamp(26px,2.6vw,36px)] leading-[1.12] font-medium tracking-[-0.025em] text-balance">
          Every incident, from report to resolved.
        </p>

        <div className="story-tilt">
          <div ref={tile} data-state="ok" className="story-edge">
            <div className={`sla-tile story-tile relative flex flex-wrap items-end justify-between gap-x-8 gap-y-4 rounded-[17px] px-6 py-6 transition-opacity duration-500 ${stage === EXIT_STAGE ? "opacity-0" : "opacity-100"}`}>
              <div className="min-w-0 flex-[1_1_220px]">
                <p className="text-[13px] text-fg-2">
                  <PriorityTag priority={scenario.priority} /> <span className="ml-1">{PRIORITY_LABEL[scenario.priority]}</span> · <span className="font-mono">{scenario.id}</span>
                </p>
                <p className="mt-2 text-[22px] leading-[1.15] font-medium tracking-[-0.02em] text-balance">{scenario.title}</p>
                <p className="mt-2 text-[13px] text-fg-2">{scenario.service}</p>
              </div>
              <div className="text-right">
                <p ref={clockCaption} className="mb-1 text-[13px]">Left to resolve</p>
                <p ref={clockText} className="story-clock font-mono leading-none font-medium tabular-nums">00:00</p>
              </div>
              <div className="h-[3px] flex-[1_1_100%] overflow-hidden rounded-sm bg-white/15">
                <span ref={bar} className="block h-full bg-fg" />
              </div>
            </div>
          </div>
          {resolved && (
            <div key={scenario.id} className="story-pop absolute -top-4 -right-3 flex items-center gap-2.5 rounded-xl bg-paper px-3.5 py-2.5 text-[13px] font-medium text-on-paper">
              <span className="block size-2 rounded-full bg-on-paper" />
              {scenario.reporter} notified: {scenario.id} resolved
            </div>
          )}
        </div>

        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="mt-5 block w-full overflow-visible" fill="none">
          <path ref={trackPath} d={TRACK} className="stroke-line" strokeWidth="2" strokeLinecap="round" />
          <path ref={trackDone} d={TRACK} pathLength={1} strokeDasharray="1 1" strokeDashoffset="1" className="stroke-fg-2" strokeWidth="2" strokeLinecap="round" />
          {nodes.map((node, index) => {
            const reached = stage >= index && stage !== EXIT_STAGE;
            const current = stage === index;
            return (
              <g key={STAGES[index].label} transform={`translate(${node.x} ${node.y})`}>
                {current && <circle r="13" className="story-ping stroke-lime" strokeWidth="1.5" />}
                <circle r="6" className={`story-node ${current ? "fill-lime" : reached ? "fill-fg" : "fill-raise"}`} />
                <text y={node.y < 50 ? -18 : 28} textAnchor="middle" className={`story-node text-[12px] ${current ? "fill-fg font-medium" : reached ? "fill-fg-2" : "fill-fg-3"}`}>
                  {STAGES[index].label}
                </text>
              </g>
            );
          })}
          <g ref={comet}>
            <circle r="11" className="fill-fg opacity-15" />
            <circle r="3.5" className="fill-paper" />
          </g>
        </svg>

        <ul className={`mt-3 h-[66px] font-mono text-xs leading-[22px] text-fg-2 transition-opacity duration-500 ${stage === EXIT_STAGE ? "opacity-0" : ""}`}>
          {visibleLines.map((line) => (
            <li key={`${scenario.id}-${line}`} className="story-rise truncate">{line}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
