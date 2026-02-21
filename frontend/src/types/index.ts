export interface Job {
  id: string;
  status:
    | "pending"
    | "awaiting_approval"
    | "processing"
    | "completed"
    | "failed";
  progress: number;
  title: string | null;
  description: string | null;
  estimated_cost: number | null;
  actual_cost: number | null;
  output_url: string | null;
  error_message: string | null;
  webhook_url: string | null;
  voiceover_text: string | null;
  music_prompt: string | null;
  include_music: boolean;
  custom_music_path: string | null;
  transition_type: string;
  created_at: string;
  updated_at: string;
  photo_count: number;
}

export interface Photo {
  id: string;
  job_id: string;
  filename: string;
  original_filename: string;
  position: number;
  created_at: string;
}

export interface CostBreakdown {
  kie_animation: number;
  google_vision: number;
  elevenlabs_voiceover: number;
  kie_suno_music: number;
}

export interface CostEstimate {
  job_id: string;
  photo_count: number;
  voiceover_chars: number;
  include_music: boolean;
  breakdown: CostBreakdown;
  total: number;
  currency: string;
}

export type WizardStep =
  | "create"
  | "upload"
  | "estimate"
  | "processing"
  | "result";
