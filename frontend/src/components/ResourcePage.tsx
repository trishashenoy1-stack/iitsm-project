import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useToast } from "./Toast";

export interface Field<T> {
  key: keyof T & string;
  label: string;
  kind?: "text" | "email" | "password" | "number" | "select" | "list";
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  required?: boolean;
  /** Only shown when adding a record. */
  createOnly?: boolean;
}

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  mono?: boolean;
}

interface ResourcePageProps<T> {
  title: string;
  description: string;
  noun: string;
  queryKey: string;
  load: () => Promise<T[]>;
  rowId: (row: T) => string;
  columns: Column<T>[];
  fields: Field<T>[];
  create?: (values: Partial<T>) => Promise<unknown>;
  update: (id: string, values: Partial<T>) => Promise<unknown>;
  toggle?: { key: keyof T & string; on: string; off: string };
}

type Editing<T> = { mode: "create" } | { mode: "edit"; row: T } | null;

/** One table-and-form pattern shared by every admin management screen. */
export function ResourcePage<T>({ title, description, noun, queryKey, load, rowId, columns, fields, create, update, toggle }: ResourcePageProps<T>) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<Editing<T>>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const { data, isPending, error: loadError } = useQuery({ queryKey: ["admin", queryKey], queryFn: load });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["admin"] });
    queryClient.invalidateQueries({ queryKey: ["services"] });
    queryClient.invalidateQueries({ queryKey: ["categories"] });
  };

  const save = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: refresh,
    onError: (e) => setError(e.message),
  });

  const visibleFields = fields.filter((f) => editing?.mode === "create" || !f.createOnly);

  function open(next: Editing<T>) {
    setError("");
    setEditing(next);
    const initial: Record<string, string> = {};
    if (next?.mode === "edit") {
      fields.forEach((f) => {
        const value = next.row[f.key];
        initial[f.key] = Array.isArray(value) ? value.join(", ") : String(value ?? "");
      });
    } else {
      fields.forEach((f) => (initial[f.key] = f.options?.[0]?.value ?? ""));
    }
    setValues(initial);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const output: Record<string, unknown> = {};
    for (const field of visibleFields) {
      const raw = (values[field.key] ?? "").trim();
      if (field.required && !raw) {
        setError(`${field.label} is required.`);
        return;
      }
      if (field.kind === "number") {
        const number = Number(raw);
        if (!Number.isInteger(number)) {
          setError(`${field.label} must be a whole number.`);
          return;
        }
        if ((field.min !== undefined && number < field.min) || (field.max !== undefined && number > field.max)) {
          setError(`${field.label} must be ${field.max === undefined ? `at least ${field.min}` : `from ${field.min} to ${field.max}`}.`);
          return;
        }
        output[field.key] = number;
      } else if (field.kind === "list") {
        output[field.key] = raw.split(",").map((part) => part.trim()).filter(Boolean);
      } else {
        output[field.key] = raw;
      }
    }
    setError("");
    const current = editing;
    if (!current) return;
    const payload = output as Partial<T>;
    const run = current.mode === "edit" ? () => update(rowId(current.row), payload) : () => create!(payload);
    save.mutate(run, {
      onSuccess: () => {
        toast(current.mode === "edit" ? "Changes saved" : `${noun} added`);
        setEditing(null);
      },
    });
  }

  function flip(row: T) {
    if (!toggle) return;
    const next = !row[toggle.key];
    setError("");
    save.mutate(() => update(rowId(row), { [toggle.key]: next } as Partial<T>), {
      onSuccess: () => toast("Changes saved"),
    });
  }

  return (
    <main className="grid grid-cols-[minmax(0,1fr)] gap-2.5">
      <header className="card flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div>
          <h1 className="text-xl font-medium tracking-tight">{title}</h1>
          <p className="text-[13px] text-fg-2">{description}</p>
        </div>
        {create && <button className="btn btn-go" onClick={() => open({ mode: "create" })}>Add {noun.toLowerCase()}</button>}
      </header>

      {editing && (
        <form onSubmit={submit} noValidate className="card grid gap-3 px-5 py-4">
          <h2 className="text-[15px] font-medium">{editing.mode === "edit" ? `Edit ${noun.toLowerCase()}` : `Add ${noun.toLowerCase()}`}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visibleFields.map((field) => (
              <label key={field.key} className="grid gap-1 text-[13px] text-fg-2">
                {field.label}
                {field.kind === "select" ? (
                  <select id={`field-${field.key}`} className="field text-fg" value={values[field.key] ?? ""} onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}>
                    {field.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input
                    id={`field-${field.key}`}
                    className="field text-fg"
                    type={field.kind === "number" || field.kind === "email" || field.kind === "password" ? field.kind : "text"}
                    autoComplete={field.kind === "password" ? "new-password" : undefined}
                    min={field.min}
                    max={field.max}
                    value={values[field.key] ?? ""}
                    onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
                  />
                )}
              </label>
            ))}
          </div>
          {error && <p role="alert" className="text-[13px] text-red">{error}</p>}
          <div className="flex gap-2">
            <button className="btn btn-go" disabled={save.isPending}>Save</button>
            <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>
      )}

      {!editing && error && <p role="alert" className="px-1 text-[13px] text-red">{error}</p>}

      <section className="card px-5 py-3">
        {isPending && <p className="py-2 text-fg-2">Loading {title.toLowerCase()}</p>}
        {loadError && <p role="alert" className="py-2 text-red">{loadError.message}</p>}
        {data && (
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-[13px]">
              <thead className="text-xs text-fg-3">
                <tr className="border-b border-line">
                  {columns.map((c) => <th key={c.header} className="py-2 pr-4 font-medium">{c.header}</th>)}
                  <th className="py-2 text-right font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((row) => (
                  <tr key={rowId(row)} className="border-b border-line last:border-0">
                    {columns.map((c) => (
                      <td key={c.header} className={`py-2.5 pr-4 wrap-anywhere ${c.mono ? "font-mono text-xs" : ""}`}>{c.cell(row)}</td>
                    ))}
                    <td className="py-2 text-right whitespace-nowrap">
                      <button className="rounded-md px-2 py-1 text-fg-2 hover:bg-raise hover:text-fg" onClick={() => open({ mode: "edit", row })}>Edit</button>
                      {toggle && (
                        <button className="ml-1 rounded-md px-2 py-1 text-fg-2 hover:bg-raise hover:text-fg" disabled={save.isPending} onClick={() => flip(row)}>
                          {row[toggle.key] ? toggle.off : toggle.on}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

export function OnOff({ on, labels = ["Active", "Inactive"] }: { on: boolean; labels?: [string, string] }) {
  return <span className={on ? "text-fg" : "text-fg-3"}>{on ? labels[0] : labels[1]}</span>;
}
