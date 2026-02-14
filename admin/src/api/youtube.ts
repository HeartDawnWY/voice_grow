import { api } from "./client";

export interface TrackProgress {
  index: number;
  title: string;
  status: string;
  error?: string;
  content_id?: number;
}

export interface DownloadTask {
  task_id: string;
  url: string;
  status: string;
  tracks: TrackProgress[];
  completed_count: number;
  failed_count: number;
  total_count: number;
  error?: string;
  created_at: number;
}

export interface YouTubeDownloadParams {
  url: string;
  content_type: string;
  category_id: number;
  artist_name?: string;
  artist_type: string;
  tag_ids?: number[];
  age_min?: number;
  age_max?: number;
}

export const youtubeApi = {
  startDownload: async (params: YouTubeDownloadParams): Promise<DownloadTask> => {
    const response = await api.post("/api/v1/admin/youtube/download", params);
    return response.data;
  },

  getTask: async (taskId: string): Promise<DownloadTask> => {
    const response = await api.get(`/api/v1/admin/youtube/tasks/${taskId}`);
    return response.data;
  },

  listTasks: async (): Promise<DownloadTask[]> => {
    const response = await api.get("/api/v1/admin/youtube/tasks");
    return response.data;
  },

  cancelTask: async (taskId: string): Promise<void> => {
    await api.post(`/api/v1/admin/youtube/tasks/${taskId}/cancel`);
  },
};
