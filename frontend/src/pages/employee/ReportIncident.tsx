import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { Level } from "../../api/types";
import { useToast } from "../../components/Toast";
import { titleCase } from "../../lib/format";

const MAX_DESCRIPTION = 2000;

const IMPACT_OPTIONS: { value: Level; label: string }[] = [
  { value: "LOW", label: "Just me" },
  { value: "MEDIUM", label: "My team" },
  { value: "HIGH", label: "Many teams or customers" },
];

const URGENCY_OPTIONS: { value: Level; label: string }[] = [
  { value: "LOW", label: "I can keep working" },
  { value: "MEDIUM", label: "It's slowing me down" },
  { value: "HIGH", label: "I can't work at all" },
];

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-[15px]">{label}</label>
      {children}
    </div>
  );
}

function Choice({ name, legend, options, value, onChange }: {
  name: string;
  legend: string;
  options: { value: Level; label: string }[];
  value: Level | null;
  onChange: (next: Level) => void;
}) {
  return (
    <fieldset className="grid gap-1.5">
      <legend className="mb-1.5 text-[15px]">{legend}</legend>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map((option) => (
          <label
            key={option.value}
            className={`cursor-pointer rounded-[10px] border px-3.5 py-3 text-[13px] has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-lime ${
              value === option.value ? "border-lime text-fg" : "border-line text-fg-2 hover:border-fg-3"
            }`}
          >
            <input type="radio" className="sr-only" name={name} checked={value === option.value} onChange={() => onChange(option.value)} />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ReportIncident() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [description, setDescription] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [category, setCategory] = useState("");
  const [impact, setImpact] = useState<Level | null>(null);
  const [urgency, setUrgency] = useState<Level | null>(null);
  const [affected, setAffected] = useState("1");
  const [error, setError] = useState("");

  const services = useQuery({ queryKey: ["services"], queryFn: api.listServices });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.listCategories });

  const create = useMutation({
    mutationFn: api.createIncident,
    onSuccess: (incident) => {
      queryClient.invalidateQueries({ queryKey: ["incidents"] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast(`Reported as ${incident.id}`);
      navigate(`/employee/incidents/${incident.id}`);
    },
    onError: (e) => setError(e.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const people = Number(affected);
    const problem = !description.trim()
      ? "Describe the problem first."
      : !serviceId
        ? "Choose the affected service."
        : !impact
          ? "Choose who is affected."
          : !urgency
            ? "Choose how much this is stopping you."
            : !Number.isInteger(people) || people < 1
              ? "Enter how many people are affected, as a whole number."
              : "";
    setError(problem);
    if (problem || !impact || !urgency) return;
    create.mutate({ description: description.trim(), serviceId, category: category || null, impact, urgency, affectedUsers: people });
  }

  return (
    <main className="max-w-[640px]">
      <h1 className="text-[32px] leading-tight font-medium tracking-[-0.022em]">Report an incident</h1>
      <p className="mt-1 text-fg-2">Tell us what's wrong. We'll work out the priority and find a technician.</p>
      {(services.error || categories.error) && (
        <p role="alert" className="mt-3 text-red">{(services.error ?? categories.error)?.message}</p>
      )}

      <form onSubmit={submit} noValidate className="mt-7 grid gap-6">
        <Field label="What's going wrong?" htmlFor="description">
          <textarea
            id="description"
            className="field min-h-[120px] resize-y"
            placeholder="The payment page shows an error when I submit a transaction."
            maxLength={MAX_DESCRIPTION}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>

        <div className="grid gap-6 sm:grid-cols-2">
          <Field label="Which service is affected?" htmlFor="service">
            <select id="service" className="field" value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
              <option value="">Choose a service</option>
              {services.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="What type of problem is it?" htmlFor="category">
            <select id="category" className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">Not sure</option>
              {categories.data?.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
            </select>
          </Field>
        </div>

        <Choice name="impact" legend="Who is affected?" options={IMPACT_OPTIONS} value={impact} onChange={setImpact} />
        <Choice name="urgency" legend="How much is this stopping you?" options={URGENCY_OPTIONS} value={urgency} onChange={setUrgency} />

        <div className="max-w-[220px]">
          <Field label="About how many people?" htmlFor="affected">
            <input id="affected" className="field" type="number" min={1} step={1} value={affected} onChange={(e) => setAffected(e.target.value)} />
          </Field>
        </div>

        {error && <p role="alert" className="text-[13px] text-red">{error}</p>}
        <div>
          <button className="btn btn-go" disabled={create.isPending}>Submit incident</button>
        </div>
      </form>
    </main>
  );
}
