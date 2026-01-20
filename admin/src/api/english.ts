import { api } from "./client";

export interface Word {
  id: number;
  word: string;
  phonetic?: string;
  translation: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  audio_us_url?: string;
  audio_uk_url?: string;
  level: string;
  category?: string;
  example_sentence?: string;
  example_translation?: string;
  created_at?: string;
}

export interface WordListParams {
  level?: string;
  category?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface WordListResponse {
  items: Word[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface WordCreateData {
  word: string;
  phonetic?: string;
  translation: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  level?: string;
  category?: string;
  example_sentence?: string;
  example_translation?: string;
}

export interface WordUpdateData {
  phonetic?: string;
  translation?: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  level?: string;
  category?: string;
  example_sentence?: string;
  example_translation?: string;
}

export const wordsApi = {
  list: async (params: WordListParams = {}): Promise<WordListResponse> => {
    const response = await api.get("/api/admin/words", { params });
    return response.data;
  },

  get: async (id: number): Promise<{ status: string; data: Word }> => {
    const response = await api.get(`/api/admin/words/${id}`);
    return response.data;
  },

  create: async (data: WordCreateData): Promise<{ status: string; data: Word }> => {
    const response = await api.post("/api/admin/words", data);
    return response.data;
  },

  update: async (id: number, data: WordUpdateData): Promise<{ status: string; data: Word }> => {
    const response = await api.put(`/api/admin/words/${id}`, data);
    return response.data;
  },

  delete: async (id: number): Promise<{ status: string; message: string }> => {
    const response = await api.delete(`/api/admin/words/${id}`);
    return response.data;
  },
};
