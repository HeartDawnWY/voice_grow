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

// ========== 搜索相关类型 ==========

export interface SearchParams {
  keyword: string;
  platforms?: string[];
  content_type?: string;
  max_results?: number;
}

export interface SearchResultItem {
  platform: string;
  url: string;
  title: string;
  duration: number;
  view_count: number;
  like_count: number;
  thumbnail?: string;
  uploader?: string;
  upload_date?: string;
  quality_score: number;
  exists_in_db: boolean;
}

export interface SearchResponse {
  results: SearchResultItem[];
  total_count: number;
  platforms_searched: string[];
  dedup_removed_count: number;
}

export interface BatchDownloadParams {
  urls: string[];
  content_type: string;
  category_id: number;
  artist_name?: string;
  artist_type: string;
  tag_ids?: number[];
  age_min?: number;
  age_max?: number;
}

export interface PlatformInfo {
  id: string;
  label: string;
}

// ========== 原有 API (保持兼容) ==========

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

// ========== 新增 API：搜索 + 批量下载 ==========

export const downloadApi = {
  search: async (params: SearchParams): Promise<SearchResponse> => {
    const response = await api.post("/api/v1/admin/download/search", params);
    return response.data;
  },

  batchDownload: async (params: BatchDownloadParams): Promise<DownloadTask> => {
    const response = await api.post("/api/v1/admin/download/batch", params);
    return response.data;
  },

  getPlatforms: async (): Promise<PlatformInfo[]> => {
    const response = await api.get("/api/v1/admin/download/platforms");
    return response.data;
  },
};
