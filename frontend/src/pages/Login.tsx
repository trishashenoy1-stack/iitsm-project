import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { homeFor, useAuth } from "../auth/AuthContext";
import { IncidentStory } from "../components/IncidentStory";
import { MOCK_PASSWORD } from "../mocks/db";

const DEMO_ACCOUNTS = [
  { label: "Employee", email: "employee@iitsm.test" },
  { label: "Technician", email: "technician@iitsm.test" },
  { label: "Admin", email: "admin@iitsm.test" },
  { label: "T101", email: "sana@iitsm.test" },
  { label: "T102", email: "dev@iitsm.test" },
  { label: "T103", email: "isha@iitsm.test" },
  { label: "T104", email: "vikram@iitsm.test" },
];

const usingMock = import.meta.env.VITE_USE_MOCK !== "false";
const WIDE_SCREEN = "(min-width: 1024px)";

function useIsWide() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE_SCREEN).matches);
  useEffect(() => {
    const query = window.matchMedia(WIDE_SCREEN);
    const update = () => setWide(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return wide;
}

/** A short horizontal shake for a failed sign-in. Keeps focus and typed values in place. */
function shake(element: HTMLElement | null) {
  if (!element || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  element.animate(
    [0, -5, 4, -3, 2, 0].map((x) => ({ transform: `translateX(${x}px)` })),
    { duration: 360, easing: "ease-in-out" },
  );
}

export function Login() {
  const { user, loading, signIn, register } = useAuth();
  const wide = useIsWide();
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const form = useRef<HTMLFormElement>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);

  if (loading) return null;
  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong. Try again.");
      shake(form.current);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    run(() => (registering ? register(name, email, password) : signIn(email, password)));
  }

  // Moves the soft light behind the form. Writes CSS variables, so React doesn't re-render.
  function trackPointer(event: PointerEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--mx", `${event.clientX - box.left}px`);
    event.currentTarget.style.setProperty("--my", `${event.clientY - box.top}px`);
  }

  const title = registering ? "Create your account" : "Welcome back";

  return (
    <main className="grid min-h-dvh lg:grid-cols-[minmax(400px,5fr)_8fr]">
      <div className="login-pane flex flex-col justify-center px-6 py-10 sm:px-12 xl:px-20" onPointerMove={trackPointer}>
        <div className="mx-auto w-full max-w-[380px]">
          <p className="enter mb-10 flex items-center gap-2.5 font-semibold tracking-tight">
            <span className="logo-mark" aria-hidden="true" />
            I-ITSM
          </p>
          <h1 key={title} aria-label={title} className="text-[38px] leading-[1.1] font-medium tracking-[-0.03em]">
            {title.split(" ").map((word, index) => (
              <span key={index} aria-hidden="true" className="word mr-[0.25em]" style={{ animationDelay: `${60 + index * 70}ms` }}>
                {word}
              </span>
            ))}
          </h1>
          <p key={`${title}-sub`} className="enter mt-2 text-fg-2" style={{ animationDelay: "200ms" }}>
            {registering ? "Report incidents and follow every fix." : "Pick up where your incidents left off."}
          </p>

          <form ref={form} onSubmit={submit} className="enter mt-7 grid" style={{ animationDelay: "260ms" }}>
            <div className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${registering ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`} inert={!registering}>
              <div className="overflow-hidden">
                <label className="grid gap-1 pb-3 text-[13px] text-fg-2">
                  Full name
                  <input id="name" className="field text-fg" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required={registering} />
                </label>
              </div>
            </div>
            <div className="grid gap-3">
              <label className="grid gap-1 text-[13px] text-fg-2">
                Work email
                <input id="email" className="field text-fg" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
              </label>
              <div className="grid gap-1 text-[13px] text-fg-2">
                <label htmlFor="password">Password</label>
                <div className="relative">
                  <input
                    id="password"
                    className="field pr-14 text-fg"
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete={registering ? "new-password" : "current-password"}
                    required
                  />
                  <button
                    type="button"
                    aria-pressed={showPassword}
                    aria-controls="password"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute inset-y-1 right-1 rounded-md px-2 text-xs text-fg-3 hover:bg-raise hover:text-fg"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
              </div>
              {error && <p role="alert" className="story-rise text-[13px] text-red">{error}</p>}
              <button className="btn btn-go btn-sheen mt-1 flex items-center justify-center gap-2 py-2.5" disabled={busy}>
                {busy ? (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    {registering ? "Creating account" : "Signing in"}
                  </>
                ) : (
                  <>
                    {registering ? "Create account" : "Sign in"}
                    <span className="btn-arrow" aria-hidden="true">→</span>
                  </>
                )}
              </button>
            </div>
          </form>

          <button
            onClick={() => {
              setRegistering(!registering);
              setError("");
            }}
            className="enter mt-3 text-[13px] text-fg-2 underline underline-offset-2 hover:text-fg"
            style={{ animationDelay: "320ms" }}
          >
            {registering ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>

          <ul className="enter mt-9 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-fg-3" style={{ animationDelay: "400ms" }}>
            {["Live SLA clocks", "Automatic assignment", "Full audit trail"].map((feature) => (
              <li key={feature} className="flex items-center gap-1.5">
                <span className="size-1 rounded-full bg-accent" aria-hidden="true" />
                {feature}
              </li>
            ))}
          </ul>

          {usingMock && (
            <div className="enter mt-6 border-t border-line pt-4" style={{ animationDelay: "460ms" }}>
              <p className="label">Mock data: open a console</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {DEMO_ACCOUNTS.map((account) => (
                  <button key={account.email} className="btn px-2.5 py-1 text-xs" disabled={busy} onClick={() => run(() => signIn(account.email, MOCK_PASSWORD))}>
                    {account.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {wide && (
        <div className="p-2.5 pl-0">
          <IncidentStory />
        </div>
      )}
    </main>
  );
}
