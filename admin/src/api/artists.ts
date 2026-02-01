import { api } from "./client";

export interface Artist {
  id: number;
  name: string;
  name_pinyin?: string;
  type: string;
  avatar?: string;
  description?: string;
  is_active?: boolean;
}

export interface ArtistListResponse {
  items: Artist[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ArtistListParams {
  type?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface ArtistCreateData {
  name: string;
  type: string;
  avatar?: string;
  description?: string;
}

export interface ArtistUpdateData {
  name?: string;
  type?: string;
  avatar?: string;
  description?: string;
  is_active?: boolean;
}

export const artistsApi = {
  list: async (params: ArtistListParams = {}): Promise<ArtistListResponse> => {
    const response = await api.get("/api/v1/admin/artists", { params });
    return response.data;
  },

  create: async (data: ArtistCreateData): Promise<Artist> => {
    const response = await api.post("/api/v1/admin/artists", data);
    return response.data;
  },

  update: async (id: number, data: ArtistUpdateData): Promise<Artist> => {
    const response = await api.put(`/api/v1/admin/artists/${id}`, data);
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/admin/artists/${id}`);
  },
};
