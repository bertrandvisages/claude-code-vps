import { Download, CheckCircle } from "lucide-react";
import type { Job } from "../types";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface Props {
  job: Job;
}

export default function VideoPlayer({ job }: Props) {
  const videoUrl = job.output_url
    ? `${API_BASE}${job.output_url}`
    : null;

  const handleDownload = () => {
    if (!videoUrl) return;
    const a = document.createElement("a");
    a.href = videoUrl;
    a.download = `${job.title ?? "montage"}.mp4`;
    a.click();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-green-600">
        <CheckCircle className="w-6 h-6" />
        <h3 className="text-lg font-semibold">Montage terminé</h3>
      </div>

      {videoUrl && (
        <div className="bg-black rounded-lg overflow-hidden">
          <video
            src={videoUrl}
            controls
            className="w-full max-h-[500px]"
          />
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">
          {job.actual_cost != null && (
            <span>
              Coût réel : <strong>${job.actual_cost.toFixed(4)}</strong>
            </span>
          )}
        </div>
        {videoUrl && (
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 bg-indigo-600 text-white py-2 px-4 rounded-lg font-medium hover:bg-indigo-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Télécharger
          </button>
        )}
      </div>
    </div>
  );
}
