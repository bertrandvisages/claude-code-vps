import { create } from "zustand";
import type { Job, CostEstimate, WizardStep } from "../types";

interface JobStore {
  currentJob: Job | null;
  estimate: CostEstimate | null;
  wizardStep: WizardStep;
  setCurrentJob: (job: Job | null) => void;
  setEstimate: (estimate: CostEstimate | null) => void;
  setWizardStep: (step: WizardStep) => void;
  reset: () => void;
}

export const useJobStore = create<JobStore>((set) => ({
  currentJob: null,
  estimate: null,
  wizardStep: "create",
  setCurrentJob: (job) => set({ currentJob: job }),
  setEstimate: (estimate) => set({ estimate }),
  setWizardStep: (step) => set({ wizardStep: step }),
  reset: () => set({ currentJob: null, estimate: null, wizardStep: "create" }),
}));
