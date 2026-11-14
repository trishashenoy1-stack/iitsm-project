import { useEffect, useState, type FormEvent } from "react";
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

export function Login() {
  const { user, loading, signIn, register } = useAuth();
  const wide = useIsWide();
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
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
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    run(() => (registering ? register(name, email, password) : signIn(email, password)));
  }

  return (
    <main className="grid min-h-dvh lg:grid-cols-[minmax(400px,5fr)_8fr]">
      <div className="flex flex-col justify-center px-6 py-10 sm:px-12 xl:px-20">
        <div className="mx-auto w-full max-w-[380px]">
          <p className="enter mb-10 font-semibold tracking-tight">I-ITSM</p>
          <h1 className="enter text-[36px] leading-tight font-medium tracking-[-0.025em]" style={{ animationDelay: "60ms" }}>
            {registering ? "Create your account" : "Sign in"}
          </h1>
          <p className="enter mt-1 text-fg-2" style={{ animationDelay: "120ms" }}>
            {registering ? "Report incidents and follow every fix." : "Pick up where your incidents left off."}
          </p>

          <form onSubmit={submit} className="enter mt-7 grid" style={{ animationDelay: "180ms" }}>
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
              <label className="grid gap-1 text-[13px] text-fg-2">
                Password
                <input id="password" className="field text-fg" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={registering ? "new-password" : "current-password"} required />
              </label>
              {error && <p role="alert" className="story-rise text-[13px] text-red">{error}</p>}
              <button className="btn btn-go btn-sheen mt-1" disabled={busy}>
                {registering ? "Create account" : "Sign in"}
              </button>
            </div>
          </form>

          <button
            onClick={() => {
              setRegistering(!registering);
              setError("");
            }}
            className="enter mt-3 text-[13px] text-fg-2 underline underline-offset-2 hover:text-fg"
            style={{ animationDelay: "240ms" }}
          >
            {registering ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>

          {usingMock && (
            <div className="enter mt-8 border-t border-line pt-4" style={{ animationDelay: "300ms" }}>
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
