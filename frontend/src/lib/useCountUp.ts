import { useEffect, useRef, useState } from "react";

const DURATION_MS = 700;

/** Animates a number from its previous value to the new one. Jumps straight there under reduced motion. */
export function useCountUp(target: number): number {
  const [shown, setShown] = useState(0);
  const from = useRef(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      from.current = target;
      setShown(target);
      return;
    }
    const start = from.current;
    const began = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - began) / DURATION_MS);
      const eased = 1 - (1 - progress) ** 3;
      const value = Math.round(start + (target - start) * eased);
      from.current = value;
      setShown(value);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return shown;
}
