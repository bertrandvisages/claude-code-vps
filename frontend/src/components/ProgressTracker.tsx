import { Loader2 } from "lucide-react";

interface Props {
  progress: number;
  status: string;
}

const statusLabels: Record<string, string> = {
  processing: "Traitement en cours",
  completed: "Terminé",
  failed: "Échec",
};

export default function ProgressTracker({ progress, status }: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        {status === "processing" && (
          <Loader2 className="w-5 h-5 text-indigo-600 animate-spin" />
        )}
        <span className="text-lg font-medium text-gray-900">
          {statusLabels[status] ?? status}
        </span>
        <span className="ml-auto text-2xl font-bold text-indigo-600">
          {progress}%
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div
          className="bg-indigo-600 h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="text-sm text-gray-500">
        Le traitement peut prendre plusieurs minutes selon le nombre de photos.
      </p>
    </div>
  );
}
