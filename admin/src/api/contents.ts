import { api } from "./client";

export type ContentType = "story" | "music" | "english";

export interface ContentTag {
  id: number;
  name: string;
  type: string;
}

export interface ContentArtist {
  id: number;
  name: string;
  role: string;
  is_primary: boolean;
}

export interface Content {
  id: number;
  type: ContentType;
  category_id: number;
  category_name?: string;
  title: string;
  title_pinyin?: string;
  subtitle?: string;
  description?: string;
  minio_path: string;
  cover_path?: string;
  play_url?: string;
  cover_url?: string;
  duration?: number;
  file_size?: number;
  format?: string;
  tags?: ContentTag[];
  artists?: ContentArtist[];
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
  category_id?: number;
  artist_id?: number;
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
  category_id: number;
  description?: string;
  minio_path?: string;
  cover_path?: string;
  duration?: number;
  tag_ids?: number[];
  artist_ids?: Array<{ id: number; role: string; is_primary: boolean }>;
  age_min?: number;
  age_max?: number;
}

export interface ContentUpdateData {
  title?: string;
  category_id?: number;
  description?: string;
  minio_path?: string;
  cover_path?: string;
  duration?: number;
  tag_ids?: number[];
  artist_ids?: Array<{ id: number; role: string; is_primary: boolean }>;
  age_min?: number;
  age_max?: number;
  is_active?: boolean;
}

export const contentsApi = {
  list: async (params: ContentListParams = {}): Promise<ContentListResponse> => {
    const response = await api.get("/api/v1/admin/contents", { params });
    return response.data;
  },

  get: async (id: number): Promise<Content> => {
    const response = await api.get(`/api/v1/admin/contents/${id}`);
    return response.data;
  },

  create: async (data: ContentCreateData): Promise<Content> => {
    const response = await api.post("/api/v1/admin/contents", data);
    return response.data;
  },

  update: async (id: number, data: ContentUpdateData): Promise<Content> => {
    const response = await api.put(`/api/v1/admin/contents/${id}`, data);
    return response.data;
  },

  delete: async (id: number, hard: boolean = false): Promise<void> => {
    await api.delete(`/api/v1/admin/contents/${id}`, { params: { hard } });
  },
};
