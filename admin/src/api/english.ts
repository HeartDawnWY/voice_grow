import { api } from "./client";

export interface Word {
  id: number;
  word: string;
  phonetic_us?: string;
  phonetic_uk?: string;
  translation: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  audio_us_url?: string;
  audio_uk_url?: string;
  level: string;
  category_id?: number;
  category_name?: string;
  example_sentence?: string;
  example_translation?: string;
  created_at?: string;
}

export interface WordListParams {
  level?: string;
  category_id?: number;
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
  phonetic_us?: string;
  phonetic_uk?: string;
  translation: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  level?: string;
  category_id?: number;
  example_sentence?: string;
  example_translation?: string;
}

export interface WordUpdateData {
  phonetic_us?: string;
  phonetic_uk?: string;
  translation?: string;
  audio_us_path?: string;
  audio_uk_path?: string;
  level?: string;
  category_id?: number;
  example_sentence?: string;
  example_translation?: string;
}

export const wordsApi = {
  list: async (params: WordListParams = {}): Promise<WordListResponse> => {
    const response = await api.get("/api/v1/admin/words", { params });
    return response.data;
  },

  get: async (id: number): Promise<Word> => {
    const response = await api.get(`/api/v1/admin/words/${id}`);
    return response.data;
  },

  create: async (data: WordCreateData): Promise<Word> => {
    const response = await api.post("/api/v1/admin/words", data);
    return response.data;
  },

  update: async (id: number, data: WordUpdateData): Promise<Word> => {
    const response = await api.put(`/api/v1/admin/words/${id}`, data);
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/admin/words/${id}`);
  },
};
