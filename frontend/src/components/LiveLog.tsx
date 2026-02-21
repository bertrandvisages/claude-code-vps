import { useEffect, useRef, useState } from "react";
import { Terminal } from "lucide-react";

interface LogEntry {
  timestamp: string;
  service: string;
  level: string;
  message: string;
}

const levelColors: Record<string, string> = {
  info: "text-gray-300",
  success: "text-green-400",
  warning: "text-yellow-400",
  error: "text-red-400",
};

const serviceBadges: Record<string, string> = {
  vision: "bg-violet-500/20 text-violet-400",
  elevenlabs: "bg-blue-500/20 text-blue-400",
  kie: "bg-orange-500/20 text-orange-400",
  ffmpeg: "bg-gray-500/20 text-gray-400",
  pipeline: "bg-indigo-500/20 text-indigo-400",
};

function formatTime(iso: string): string {
  const d = new Date(iso + "Z");
  return d.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function LiveLog({ jobId }: { jobId: string }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000";
    const es = new EventSource(`${baseURL}/api/v1/jobs/${jobId}/logs`);

    es.onopen = () => setConnected(true);

    es.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        setLogs((prev) => [...prev, entry]);
      } catch {
        // Ignore malformed messages
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [jobId]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="rounded-lg overflow-hidden border border-gray-700">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2 bg-gray-800 border-b border-gray-700">
        <Terminal className="w-4 h-4 text-gray-400" />
        <span className="text-sm font-medium text-gray-300">
          Journal en temps réel
        </span>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-gray-500">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-500" : "bg-gray-600"
            }`}
          />
          {connected ? "Connecté" : "Déconnecté"}
        </span>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        className="bg-gray-900 px-4 py-3 h-72 overflow-y-auto font-mono text-xs leading-relaxed space-y-0.5"
      >
        {logs.length === 0 && (
          <p className="text-gray-600 italic">En attente des logs...</p>
        )}
        {logs.map((entry, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="text-gray-600 shrink-0">
              {formatTime(entry.timestamp)}
            </span>
            <span
              className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                serviceBadges[entry.service] ?? "bg-gray-500/20 text-gray-400"
              }`}
            >
              {entry.service}
            </span>
            <span className={levelColors[entry.level] ?? "text-gray-300"}>
              {entry.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
