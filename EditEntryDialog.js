import React, { useEffect, useState } from "react";
import api, { formatApiError } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";

function isoToParts(iso) {
  if (!iso) return { date: "", time: "" };
  const d = new Date(iso);
  const date = d.toISOString().slice(0, 10);
  const time = d.toTimeString().slice(0, 5);
  return { date, time };
}

function partsToISO(date, time) {
  if (!date || !time) return null;
  return new Date(`${date}T${time}:00`).toISOString();
}

export default function EditEntryDialog({ entry, projects, open, onOpenChange, onUpdated }) {
  const [form, setForm] = useState({
    date: "",
    start_time: "",
    end_time: "",
    project_id: "none",
    task: "",
    notes: "",
    billable: true,
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!entry) return;
    const s = isoToParts(entry.start_at);
    const e = isoToParts(entry.end_at);
    setForm({
      date: s.date,
      start_time: s.time,
      end_time: e.time || s.time,
      project_id: entry.project_id || "none",
      task: entry.task || "",
      notes: entry.notes || "",
      billable: entry.billable !== false,
    });
  }, [entry]);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!entry) return;
    setLoading(true);
    try {
      const startISO = partsToISO(form.date, form.start_time);
      const endISO = partsToISO(form.date, form.end_time);
      if (!startISO || !endISO || new Date(endISO) <= new Date(startISO)) {
        toast.error("End time must be after start time");
        setLoading(false);
        return;
      }
      await api.patch(`/entries/${entry.id}`, {
        project_id: form.project_id === "none" ? "" : form.project_id,
        task: form.task,
        notes: form.notes,
        billable: form.billable,
        start_at: startISO,
        end_at: endISO,
      });
      toast.success("Entry updated");
      onOpenChange(false);
      onUpdated?.();
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="edit-entry-dialog">
        <DialogHeader>
          <DialogTitle className="font-heading text-2xl font-black tracking-tighter">Edit entry</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4 mt-2">
          <div>
            <Label>Date</Label>
            <Input type="date" value={form.date} onChange={(e) => update("date", e.target.value)} required data-testid="edit-date-input" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Start</Label>
              <Input type="time" value={form.start_time} onChange={(e) => update("start_time", e.target.value)} required data-testid="edit-start-input" />
            </div>
            <div>
              <Label>End</Label>
              <Input type="time" value={form.end_time} onChange={(e) => update("end_time", e.target.value)} required data-testid="edit-end-input" />
            </div>
          </div>
          <div>
            <Label>Project</Label>
            <Select value={form.project_id} onValueChange={(v) => update("project_id", v)}>
              <SelectTrigger data-testid="edit-project-select">
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
            <Input value={form.task} onChange={(e) => update("task", e.target.value)} placeholder="e.g. Implement API" data-testid="edit-task-input" />
          </div>
          <div>
            <Label>Notes</Label>
            <Textarea value={form.notes} onChange={(e) => update("notes", e.target.value)} placeholder="Optional" data-testid="edit-notes-input" />
          </div>
          <div className="flex items-center justify-between border border-gray-200 px-3 py-2 rounded-md">
            <div>
              <div className="text-sm font-medium">Billable</div>
              <div className="text-xs text-gray-500">Counts toward client invoices</div>
            </div>
            <Switch checked={form.billable} onCheckedChange={(v) => update("billable", v)} data-testid="edit-billable-toggle" />
          </div>
          <Button type="submit" disabled={loading} className="w-full bg-black hover:bg-gray-800 text-white" data-testid="edit-submit-btn">
            {loading ? "Saving…" : "Save changes"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
