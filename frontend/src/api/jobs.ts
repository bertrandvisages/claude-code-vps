import apiClient from "./client";
import type { Job, CostEstimate } from "../types";

export const createJob = (data: {
  title?: string;
  description?: string;
  voiceover_text?: string;
  music_prompt?: string;
  include_music?: boolean;
  transition_type?: string;
}) => apiClient.post<Job>("/api/v1/jobs/", data);

export const getJob = (id: string) =>
  apiClient.get<Job>(`/api/v1/jobs/${id}`);

export const listJobs = (status?: string) =>
  apiClient.get<Job[]>("/api/v1/jobs/", { params: status ? { status } : {} });

export const deleteJob = (id: string) =>
  apiClient.delete(`/api/v1/jobs/${id}`);

export const estimateJob = (id: string) =>
  apiClient.post<CostEstimate>(`/api/v1/jobs/${id}/estimate`);

export const approveJob = (id: string, approved: boolean) =>
  apiClient.post<Job>(`/api/v1/jobs/${id}/approve`, { approved });

export const processJob = (id: string) =>
  apiClient.post<Job>(`/api/v1/jobs/${id}/process`);

export const uploadMusic = (jobId: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient.post<Job>(`/api/v1/jobs/${jobId}/music`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const deleteMusic = (jobId: string) =>
  apiClient.delete(`/api/v1/jobs/${jobId}/music`);
