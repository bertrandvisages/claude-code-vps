import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Film, Loader2 } from "lucide-react";
import { listJobs } from "../api/jobs";
import type { Job } from "../types";

const statusConfig: Record<string, { label: string; color: string }> = {
  pending: { label: "En attente", color: "bg-gray-100 text-gray-700" },
  awaiting_approval: {
    label: "À approuver",
    color: "bg-yellow-100 text-yellow-700",
  },
  processing: { label: "En cours", color: "bg-blue-100 text-blue-700" },
  completed: { label: "Terminé", color: "bg-green-100 text-green-700" },
  failed: { label: "Échec", color: "bg-red-100 text-red-700" },
};

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listJobs()
      .then(({ data }) =>
        setJobs(data.sort((a, b) => b.created_at.localeCompare(a.created_at)))
      )
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Mes montages</h2>
        <Link
          to="/jobs/new"
          className="flex items-center gap-2 bg-indigo-600 text-white py-2 px-4 rounded-lg font-medium hover:bg-indigo-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Nouveau montage
        </Link>
      </div>

      {jobs.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
          <Film className="w-12 h-12 mx-auto text-gray-300 mb-4" />
          <p className="text-gray-500 text-lg">Aucun montage pour l'instant</p>
          <p className="text-gray-400 text-sm mt-1">
            Créez votre premier montage vidéo en cliquant sur le bouton
            ci-dessus.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => {
            const status = statusConfig[job.status] ?? {
              label: job.status,
              color: "bg-gray-100 text-gray-700",
            };
            return (
              <Link
                key={job.id}
                to={`/jobs/${job.id}`}
                className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Film className="w-5 h-5 text-gray-400" />
                    <div>
                      <p className="font-medium text-gray-900">
                        {job.title ?? "Sans titre"}
                      </p>
                      <p className="text-sm text-gray-500">
                        {job.photo_count} photo
                        {job.photo_count !== 1 ? "s" : ""} —{" "}
                        {new Date(job.created_at).toLocaleDateString("fr-FR", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                    </div>
                  </div>
                  <span
                    className={`text-xs font-medium px-2.5 py-1 rounded-full ${status.color}`}
                  >
                    {status.label}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
