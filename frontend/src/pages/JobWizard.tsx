import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { AlertCircle, ArrowLeft, Music, X } from "lucide-react";
import { useJobStore } from "../stores/jobStore";
import {
  createJob,
  getJob,
  estimateJob,
  approveJob,
  processJob,
  uploadMusic,
} from "../api/jobs";
import PhotoUploader from "../components/PhotoUploader";
import ProgressTracker from "../components/ProgressTracker";
import LiveLog from "../components/LiveLog";
import CostEstimateView from "../components/CostEstimateView";
import VideoPlayer from "../components/VideoPlayer";
import type { WizardStep } from "../types";

function statusToStep(status: string): WizardStep {
  switch (status) {
    case "pending":
      return "upload";
    case "awaiting_approval":
      return "estimate";
    case "processing":
      return "processing";
    case "completed":
      return "result";
    case "failed":
      return "result";
    default:
      return "upload";
  }
}

export default function JobWizard() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isNew = !id || id === "new";

  const {
    currentJob,
    estimate,
    wizardStep,
    setCurrentJob,
    setEstimate,
    setWizardStep,
    reset,
  } = useJobStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [photoCount, setPhotoCount] = useState(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Form state
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [voiceoverText, setVoiceoverText] = useState("");
  const [transitionType, setTransitionType] = useState("crossfade");
  const [musicSource, setMusicSource] = useState<"none" | "upload" | "suno">("none");
  const [musicFile, setMusicFile] = useState<File | null>(null);
  const [musicPrompt, setMusicPrompt] = useState("");
  const musicInputRef = useRef<HTMLInputElement>(null);

  // Load existing job
  useEffect(() => {
    if (isNew) {
      reset();
      setWizardStep("create");
      return;
    }
    setLoading(true);
    getJob(id)
      .then(({ data }) => {
        setCurrentJob(data);
        setWizardStep(statusToStep(data.status));
        setPhotoCount(data.photo_count);
      })
      .catch(() => setError("Impossible de charger le job."))
      .finally(() => setLoading(false));

    return () => reset();
  }, [id, isNew]);

  // Polling for processing status
  const startPolling = useCallback(
    (jobId: string) => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      pollingRef.current = setInterval(async () => {
        try {
          const { data } = await getJob(jobId);
          setCurrentJob(data);
          if (data.status === "completed" || data.status === "failed") {
            if (pollingRef.current) clearInterval(pollingRef.current);
            pollingRef.current = null;
            setWizardStep("result");
          }
        } catch {
          // Ignore polling errors
        }
      }, 3000);
    },
    [setCurrentJob, setWizardStep]
  );

  useEffect(() => {
    if (wizardStep === "processing" && currentJob) {
      startPolling(currentJob.id);
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [wizardStep, currentJob?.id, startPolling]);

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      const includeMusic = musicSource !== "none";
      const { data } = await createJob({
        title: title || undefined,
        description: description || undefined,
        voiceover_text: voiceoverText || undefined,
        music_prompt: musicSource === "suno" && musicPrompt ? musicPrompt : undefined,
        include_music: includeMusic,
        transition_type: transitionType,
      });

      // Upload la musique custom si sélectionnée
      if (musicSource === "upload" && musicFile) {
        const { data: updatedJob } = await uploadMusic(data.id, musicFile);
        setCurrentJob(updatedJob);
      } else {
        setCurrentJob(data);
      }

      setWizardStep("upload");
      navigate(`/jobs/${data.id}`, { replace: true });
    } catch {
      setError("Erreur lors de la création du job.");
    } finally {
      setLoading(false);
    }
  };

  const handleEstimate = async () => {
    if (!currentJob) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await estimateJob(currentJob.id);
      setEstimate(data);
      setWizardStep("estimate");
    } catch {
      setError("Erreur lors de l'estimation du coût.");
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!currentJob) return;
    setLoading(true);
    setError(null);
    try {
      await approveJob(currentJob.id, true);
      const { data } = await processJob(currentJob.id);
      setCurrentJob(data);
      setWizardStep("processing");
    } catch {
      setError("Erreur lors du lancement du traitement.");
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!currentJob) return;
    setLoading(true);
    try {
      await approveJob(currentJob.id, false);
      navigate("/");
    } catch {
      setError("Erreur lors du rejet.");
    } finally {
      setLoading(false);
    }
  };

  if (loading && !currentJob) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Step: Create */}
      {wizardStep === "create" && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">Nouveau montage</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Titre
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Mon montage vidéo"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description optionnelle"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Texte de voix off
              </label>
              <textarea
                value={voiceoverText}
                onChange={(e) => setVoiceoverText(e.target.value)}
                placeholder="Le texte qui sera lu en voix off sur la vidéo..."
                rows={4}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Musique de fond
              </label>
              <div className="flex gap-1 mb-3">
                <button
                  type="button"
                  onClick={() => {
                    setMusicSource("none");
                    setMusicFile(null);
                    setMusicPrompt("");
                    if (musicInputRef.current) musicInputRef.current.value = "";
                  }}
                  className={`flex-1 py-1.5 px-3 text-sm rounded-lg border transition-colors ${
                    musicSource === "none"
                      ? "bg-gray-900 text-white border-gray-900"
                      : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
                  }`}
                >
                  Aucune
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMusicSource("upload");
                    setMusicPrompt("");
                  }}
                  className={`flex-1 py-1.5 px-3 text-sm rounded-lg border transition-colors ${
                    musicSource === "upload"
                      ? "bg-gray-900 text-white border-gray-900"
                      : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
                  }`}
                >
                  Fichier audio
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMusicSource("suno");
                    setMusicFile(null);
                    if (musicInputRef.current) musicInputRef.current.value = "";
                  }}
                  className={`flex-1 py-1.5 px-3 text-sm rounded-lg border transition-colors ${
                    musicSource === "suno"
                      ? "bg-gray-900 text-white border-gray-900"
                      : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
                  }`}
                >
                  Suno IA
                </button>
              </div>

              {musicSource === "upload" && (
                <>
                  <input
                    ref={musicInputRef}
                    type="file"
                    accept=".mp3,.wav"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) setMusicFile(file);
                    }}
                  />
                  {musicFile ? (
                    <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3">
                      <Music className="w-5 h-5 text-indigo-600 shrink-0" />
                      <span className="text-sm text-indigo-900 truncate flex-1">
                        {musicFile.name}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setMusicFile(null);
                          if (musicInputRef.current) musicInputRef.current.value = "";
                        }}
                        className="text-indigo-400 hover:text-indigo-600"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => musicInputRef.current?.click()}
                      className="w-full border-2 border-dashed border-gray-300 rounded-lg px-4 py-3 text-sm text-gray-500 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
                    >
                      Cliquer pour ajouter un fichier audio (MP3, WAV)
                    </button>
                  )}
                  <p className="text-xs text-gray-400 mt-1">
                    La musique sera ajustée et fondue sur les 3 dernières secondes
                  </p>
                </>
              )}

              {musicSource === "suno" && (
                <>
                  <textarea
                    value={musicPrompt}
                    onChange={(e) => setMusicPrompt(e.target.value)}
                    placeholder="Ex: Musique douce au piano, ambiance chaleureuse et nostalgique..."
                    rows={2}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
                  />
                  <p className="text-xs text-gray-400 mt-1">
                    Décrivez l'ambiance musicale souhaitée — générée par Suno via Kie.ai
                  </p>
                </>
              )}
            </div>

            <div className="flex items-center justify-end">
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium text-gray-700">
                  Transition
                </label>
                <select
                  value={transitionType}
                  onChange={(e) => setTransitionType(e.target.value)}
                  className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                >
                  <option value="crossfade">Fondu enchaîné</option>
                  <option value="cut">Coupe franche</option>
                </select>
              </div>
            </div>
          </div>

          <button
            onClick={handleCreate}
            disabled={loading}
            className="w-full bg-indigo-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Création..." : "Créer le job"}
          </button>
        </div>
      )}

      {/* Step: Upload */}
      {wizardStep === "upload" && currentJob && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">
            Ajouter des photos
          </h2>
          <p className="text-gray-500">
            Glissez vos photos dans la zone ci-dessous. Elles seront utilisées
            pour générer les clips animés du montage.
          </p>

          <PhotoUploader
            jobId={currentJob.id}
            onPhotosChange={setPhotoCount}
          />

          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">
              {photoCount} photo{photoCount !== 1 ? "s" : ""} uploadée
              {photoCount !== 1 ? "s" : ""}
            </span>
            <button
              onClick={handleEstimate}
              disabled={loading || photoCount === 0}
              className="bg-indigo-600 text-white py-2 px-4 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {loading ? "Estimation..." : "Estimer le coût"}
            </button>
          </div>
        </div>
      )}

      {/* Step: Estimate */}
      {wizardStep === "estimate" && estimate && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">
            Estimation du coût
          </h2>
          <CostEstimateView
            estimate={estimate}
            onApprove={handleApprove}
            onReject={handleReject}
            loading={loading}
          />
        </div>
      )}

      {/* Step: Processing */}
      {wizardStep === "processing" && currentJob && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-gray-900">
            Traitement en cours
          </h2>
          <ProgressTracker
            progress={currentJob.progress}
            status={currentJob.status}
          />
          <LiveLog jobId={currentJob.id} />
        </div>
      )}

      {/* Step: Result */}
      {wizardStep === "result" && currentJob && (
        <div className="space-y-6">
          {currentJob.status === "failed" ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-red-600">
                <AlertCircle className="w-6 h-6" />
                <h3 className="text-lg font-semibold">
                  Le traitement a échoué
                </h3>
              </div>
              {currentJob.error_message && (
                <p className="text-sm text-gray-600 bg-red-50 border border-red-200 rounded-lg p-4">
                  {currentJob.error_message}
                </p>
              )}
            </div>
          ) : (
            <VideoPlayer job={currentJob} />
          )}

          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Retour au dashboard
          </button>
        </div>
      )}
    </div>
  );
}
