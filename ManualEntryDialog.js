import React, { useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { Plus } from "lucide-react";

function toISO(dateStr, timeStr) {
  return new Date(`${dateStr}T${timeStr}:00`).toISOString();
}

export default function ManualEntryDialog({ projects, onCreated, triggerLabel = "Add Manual Entry" }) {
  const [open, setOpen] = useState(false);
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    date: today,
    start_time: "09:00",
    end_time: "10:00",
    project_id: "none",
    task: "",
    notes: "",
    billable: true,
  });
  const [loading, setLoading] = useState(false);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/entries", {
        project_id: form.project_id === "none" ? null : form.project_id,
        task: form.task,
        notes: form.notes,
        billable: form.billable,
        start_at: toISO(form.date, form.start_time),
        end_at: toISO(form.date, form.end_time),
      });
      toast.success("Entry added");
      setOpen(false);
      setForm({ ...form, task: "", notes: "" });
      onCreated?.();
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="open-manual-entry-btn" className="bg-black hover:bg-gray-800 text-white h-10">
          <Plus size={14} className="mr-1.5" /> {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md" data-testid="manual-entry-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading text-2xl font-black tracking-tighter">Add manual entry</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4 mt-2">
          <div>
            <Label>Date</Label>
            <Input type="date" value={form.date} onChange={(e) => update("date", e.target.value)} required data-testid="manual-date-input" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Start</Label>
              <Input type="time" value={form.start_time} onChange={(e) => update("start_time", e.target.value)} required data-testid="manual-start-input" />
            </div>
            <div>
              <Label>End</Label>
              <Input type="time" value={form.end_time} onChange={(e) => update("end_time", e.target.value)} required data-testid="manual-end-input" />
            </div>
          </div>
          <div>
            <Label>Project</Label>
            <Select value={form.project_id} onValueChange={(v) => update("project_id", v)}>
              <SelectTrigger data-testid="manual-project-select">
                <SelectValue placeholder="Select project" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No project</SelectItem>
                {projects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Task</Label>
            <Input value={form.task} onChange={(e) => update("task", e.target.value)} placeholder="e.g. Implement API" data-testid="manual-task-input" />
          </div>
          <div>
            <Label>Notes</Label>
            <Textarea value={form.notes} onChange={(e) => update("notes", e.target.value)} placeholder="Optional" data-testid="manual-notes-input" />
          </div>
          <div className="flex items-center justify-between border border-gray-200 px-3 py-2 rounded-md">
            <div>
              <div className="text-sm font-medium">Billable</div>
              <div className="text-xs text-gray-500">Counts toward client invoices</div>
            </div>
            <Switch checked={form.billable} onCheckedChange={(v) => update("billable", v)} data-testid="manual-billable-toggle" />
          </div>
          <Button type="submit" disabled={loading} className="w-full bg-black hover:bg-gray-800 text-white" data-testid="manual-submit-btn">
            {loading ? "Saving…" : "Save entry"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
