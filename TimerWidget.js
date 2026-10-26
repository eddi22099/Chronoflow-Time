import React, { useEffect, useState, useCallback } from "react";
import api, { formatApiError, minutesToHM } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Play, Square } from "lucide-react";
import { toast } from "sonner";

export default function TimerWidget({ projects, onChange }) {
  const [active, setActive] = useState(null);
  const [projectId, setProjectId] = useState("none");
  const [task, setTask] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [loading, setLoading] = useState(false);

  const fetchActive = useCallback(async () => {
    try {
      const { data } = await api.get("/timer/active");
      setActive(data.active);
      if (data.active) {
        setProjectId(data.active.project_id || "none");
        setTask(data.active.task || "");
      }
    } catch (err) {
      console.warn("Failed to fetch active timer:", err?.message);
    }
  }, []);

  useEffect(() => { fetchActive(); }, [fetchActive]);

  useEffect(() => {
    if (!active) { setElapsed(0); return; }
    const start = new Date(active.start_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [active]);

  const fmt = (s) => {
    const h = Math.floor(s / 3600).toString().padStart(2, "0");
    const m = Math.floor((s % 3600) / 60).toString().padStart(2, "0");
    const sec = (s % 60).toString().padStart(2, "0");
    return `${h}:${m}:${sec}`;
  };

  const start = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/timer/start", {
        project_id: projectId === "none" ? null : projectId,
        task,
      });
      setActive(data);
      toast.success("Timer started");
      onChange?.();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  const stop = async () => {
    setLoading(true);
    try {
      await api.post("/timer/stop");
      setActive(null);
      setTask("");
      toast.success("Time logged");
      onChange?.();
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border border-gray-200 p-6 lg:p-8" data-testid="timer-widget">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-[0.2em] text-gray-500">Live Timer</div>
        <div className={`flex items-center gap-2 text-xs uppercase tracking-wider font-bold ${active ? "text-[#34c759]" : "text-gray-400"}`}>
          <span className={`w-2 h-2 rounded-full ${active ? "bg-[#34c759] timer-pulse" : "bg-gray-300"}`} />
          {active ? "Running" : "Idle"}
        </div>
      </div>

      <div className="mt-3 font-heading font-black tracking-tighter leading-none text-6xl lg:text-7xl tabular-nums" data-testid="timer-display">
        {fmt(elapsed)}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-6">
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-gray-500 mb-1.5">Project</div>
          <Select value={projectId} onValueChange={setProjectId} disabled={!!active}>
            <SelectTrigger data-testid="timer-project-select" className="h-10">
              <SelectValue placeholder="Select project" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No project</SelectItem>
              {projects.map((p) => (
                <SelectItem key={p.id} value={p.id} data-testid={`timer-project-option-${p.id}`}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.18em] text-gray-500 mb-1.5">Task</div>
          <Input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="What are you working on?"
            disabled={!!active}
            data-testid="timer-task-input"
            className="h-10"
          />
        </div>
      </div>

      <div className="mt-5">
        {active ? (
          <Button
            onClick={stop}
            disabled={loading}
            data-testid="timer-stop-btn"
            className="w-full h-12 bg-[#ff3b30] hover:bg-red-700 text-white text-base font-semibold"
          >
            <Square size={16} className="mr-2 fill-white" /> Clock Out
          </Button>
        ) : (
          <Button
            onClick={start}
            disabled={loading}
            data-testid="timer-start-btn"
            className="w-full h-12 bg-[#34c759] hover:bg-green-700 text-white text-base font-semibold"
          >
            <Play size={16} className="mr-2 fill-white" /> Clock In
          </Button>
        )}
      </div>
      {active && (
        <div className="mt-3 text-xs font-mono text-gray-500" data-testid="timer-started-at">
          Started {new Date(active.start_at).toLocaleTimeString()} · {minutesToHM(Math.floor(elapsed / 60))}
        </div>
      )}
    </div>
  );
}
