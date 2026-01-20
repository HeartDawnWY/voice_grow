import { api } from "./client";

export type ContentType = "story" | "music" | "english";

export interface Content {
  id: number;
  type: ContentType;
  category: string;
  title: string;
  description?: string;
  minio_path: string;
  cover_path?: string;
  play_url?: string;
  cover_url?: string;
  duration?: number;
  file_size?: number;
  format?: string;
  tags?: string;
  age_min: number;
  age_max: number;
  play_count: number;
  like_count: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ContentListParams {
  type?: string;
  category?: string;
  keyword?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
}

export interface ContentListResponse {
  items: Content[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ContentCreateData {
  type: string;
  title: string;
  category?: string;
  description?: string;
  minio_path?: string;
  cover_path?: string;
  duration?: number;
  tags?: string;
  age_min?: number;
  age_max?: number;
}

export interface ContentUpdateData {
  title?: string;
  category?: string;
  description?: string;
  minio_path?: string;
  cover_path?: string;
  duration?: number;
  tags?: string;
  age_min?: number;
  age_max?: number;
  is_active?: boolean;
}

export const contentsApi = {
  list: async (params: ContentListParams = {}): Promise<ContentListResponse> => {
    const response = await api.get("/api/admin/contents", { params });
    return response.data;
  },

  get: async (id: number): Promise<{ status: string; data: Content }> => {
    const response = await api.get(`/api/admin/contents/${id}`);
    return response.data;
  },

  create: async (data: ContentCreateData): Promise<{ status: string; data: Content }> => {
    const response = await api.post("/api/admin/contents", data);
    return response.data;
  },

  update: async (id: number, data: ContentUpdateData): Promise<{ status: string; data: Content }> => {
    const response = await api.put(`/api/admin/contents/${id}`, data);
    return response.data;
  },

  delete: async (id: number, hard: boolean = false): Promise<{ status: string; message: string }> => {
    const response = await api.delete(`/api/admin/contents/${id}`, { params: { hard } });
    return response.data;
  },
};
