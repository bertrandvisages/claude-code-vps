import { DollarSign } from "lucide-react";
import type { CostEstimate } from "../types";

interface Props {
  estimate: CostEstimate;
  onApprove: () => void;
  onReject: () => void;
  loading: boolean;
}

const breakdownLabels: Record<string, string> = {
  kie_animation: "Animation Kie.ai",
  google_vision: "Analyse Google Vision",
  elevenlabs_voiceover: "Voix off ElevenLabs",
  kie_suno_music: "Musique Suno (Kie.ai)",
};

export default function CostEstimateView({
  estimate,
  onApprove,
  onReject,
  loading,
}: Props) {
  return (
    <div className="space-y-6">
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-center gap-2 mb-4">
          <DollarSign className="w-5 h-5 text-indigo-600" />
          <h3 className="text-lg font-semibold text-gray-900">
            Estimation du coût
          </h3>
        </div>

        <div className="space-y-2 mb-4">
          {Object.entries(estimate.breakdown).map(([key, value]) => (
            <div key={key} className="flex justify-between text-sm">
              <span className="text-gray-600">
                {breakdownLabels[key] ?? key}
              </span>
              <span className="text-gray-900 font-mono">
                ${value.toFixed(4)}
              </span>
            </div>
          ))}
        </div>

        <div className="border-t border-gray-200 pt-3 flex justify-between">
          <span className="font-semibold text-gray-900">Total</span>
          <span className="font-bold text-lg text-indigo-600">
            ${estimate.total.toFixed(4)} {estimate.currency}
          </span>
        </div>

        <p className="text-xs text-gray-400 mt-2">
          {estimate.photo_count} photos — {estimate.voiceover_chars} caractères
          voix off
        </p>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onApprove}
          disabled={loading}
          className="flex-1 bg-indigo-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "Lancement..." : "Approuver et lancer"}
        </button>
        <button
          onClick={onReject}
          disabled={loading}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          Rejeter
        </button>
      </div>
    </div>
  );
}
