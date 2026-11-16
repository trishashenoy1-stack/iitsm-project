import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import type { AssignmentStrategyId } from "../../api/types";
import { useToast } from "../../components/Toast";

export function AssignmentPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [choice, setChoice] = useState<AssignmentStrategyId | null>(null);
  const { data, isPending, error } = useQuery({ queryKey: ["admin", "assignment"], queryFn: api.admin.assignment });

  const save = useMutation({
    mutationFn: api.admin.setAssignment,
    onSuccess: (updated) => {
      queryClient.setQueryData(["admin", "assignment"], updated);
      setChoice(null);
      toast("Assignment strategy saved");
    },
  });

  if (isPending) return <p className="p-4 text-fg-2">Loading settings</p>;
  if (error) return <p role="alert" className="p-4 text-red">{error.message}</p>;
  const selected = choice ?? data.current;

  return (
    <main className="card grid max-w-[720px] gap-4 px-5 py-4">
      <div>
        <h1 className="text-xl font-medium tracking-tight">Assignment strategy</h1>
        <p className="text-[13px] text-fg-2">Applies to new incidents. If nobody matches, the least busy technician is used.</p>
      </div>
      <fieldset className="grid gap-2">
        <legend className="sr-only">Assignment strategy</legend>
        {data.options.map((option) => (
          <label
            key={option.id}
            className={`cursor-pointer rounded-[10px] border px-4 py-3 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-lime ${
              selected === option.id ? "border-lime" : "border-line hover:border-fg-3"
            }`}
          >
            <input type="radio" name="strategy" className="sr-only" checked={selected === option.id} onChange={() => setChoice(option.id)} />
            <span className="block font-medium">
              {option.label}
              {option.id === data.current && <span className="ml-2 text-xs font-normal text-fg-3">Current</span>}
            </span>
            <span className="block text-[13px] text-fg-2">{option.description}</span>
          </label>
        ))}
      </fieldset>
      {save.error && <p role="alert" className="text-[13px] text-red">{save.error.message}</p>}
      <div>
        <button className="btn btn-go" disabled={save.isPending || selected === data.current} onClick={() => save.mutate(selected)}>
          Save strategy
        </button>
      </div>
    </main>
  );
}
