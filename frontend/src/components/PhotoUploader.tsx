import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, X, Image } from "lucide-react";
import { uploadPhoto, deletePhoto } from "../api/photos";
import type { Photo } from "../types";

interface Props {
  jobId: string;
  onPhotosChange: (count: number) => void;
}

export default function PhotoUploader({ jobId, onPhotosChange }: Props) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [uploading, setUploading] = useState(false);

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      setUploading(true);
      const newPhotos: Photo[] = [];
      for (const file of acceptedFiles) {
        try {
          const { data } = await uploadPhoto(jobId, file);
          newPhotos.push(data);
        } catch (err) {
          console.error("Upload failed:", err);
        }
      }
      setPhotos((prev) => {
        const updated = [...prev, ...newPhotos];
        onPhotosChange(updated.length);
        return updated;
      });
      setUploading(false);
    },
    [jobId, onPhotosChange]
  );

  const handleDelete = async (photoId: string) => {
    try {
      await deletePhoto(jobId, photoId);
      setPhotos((prev) => {
        const updated = prev.filter((p) => p.id !== photoId);
        onPhotosChange(updated.length);
        return updated;
      });
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
      "image/webp": [".webp"],
    },
    maxSize: 10 * 1024 * 1024,
  });

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? "border-indigo-500 bg-indigo-50"
            : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <input {...getInputProps()} />
        <Upload className="w-10 h-10 mx-auto text-gray-400 mb-3" />
        {uploading ? (
          <p className="text-gray-600">Upload en cours...</p>
        ) : isDragActive ? (
          <p className="text-indigo-600 font-medium">
            Relâchez pour uploader
          </p>
        ) : (
          <>
            <p className="text-gray-600 font-medium">
              Glissez vos photos ici ou cliquez pour sélectionner
            </p>
            <p className="text-gray-400 text-sm mt-1">
              JPG, PNG, WebP — 10 Mo max par photo
            </p>
          </>
        )}
      </div>

      {photos.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {photos.map((photo) => (
            <div
              key={photo.id}
              className="relative group bg-gray-100 rounded-lg p-3 flex items-center gap-2"
            >
              <Image className="w-5 h-5 text-gray-400 shrink-0" />
              <span className="text-sm text-gray-700 truncate">
                {photo.original_filename}
              </span>
              <button
                onClick={() => handleDelete(photo.id)}
                className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
