import apiClient from "./client";
import type { Photo } from "../types";

export const uploadPhoto = (jobId: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiClient.post<Photo>(`/api/v1/jobs/${jobId}/photos/`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const listPhotos = (jobId: string) =>
  apiClient.get<Photo[]>(`/api/v1/jobs/${jobId}/photos/`);

export const deletePhoto = (jobId: string, photoId: string) =>
  apiClient.delete(`/api/v1/jobs/${jobId}/photos/${photoId}`);
