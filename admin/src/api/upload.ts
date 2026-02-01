import { api } from "./client";
import axios from "axios";

export interface PresignedUrlResponse {
  upload_url: string;
  object_name: string;
}

export type UploadFolder = "stories" | "music" | "english" | "covers";

export const uploadApi = {
  getPresignedUrl: async (
    filename: string,
    folder: UploadFolder
  ): Promise<PresignedUrlResponse> => {
    const response = await api.post("/api/v1/admin/upload/presigned-url", null, {
      params: { filename, folder },
    });
    return response.data;
  },

  uploadFile: async (
    file: File,
    folder: UploadFolder,
    onProgress?: (percent: number) => void
  ): Promise<string> => {
    // 1. Get presigned URL
    const { upload_url, object_name } = await uploadApi.getPresignedUrl(file.name, folder);

    // 2. Upload file directly to MinIO
    await axios.put(upload_url, file, {
      headers: {
        "Content-Type": file.type || "application/octet-stream",
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percent);
        }
      },
    });

    // 3. Return the object path
    return object_name;
  },
};
