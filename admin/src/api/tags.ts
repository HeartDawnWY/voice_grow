import { api } from "./client";

export interface Tag {
  id: number;
  name: string;
  name_pinyin?: string;
  type: string;
  color?: string;
  sort_order?: number;
  is_active?: boolean;
}

export interface TagCreateData {
  name: string;
  type: string;
  color?: string;
  sort_order?: number;
}

export interface TagUpdateData {
  name?: string;
  color?: string;
  sort_order?: number;
  is_active?: boolean;
}

export const tagsApi = {
  list: async (type?: string): Promise<Tag[]> => {
    const params = type ? { type } : {};
    const response = await api.get("/api/v1/admin/tags", { params });
    return response.data.tags ?? response.data;
  },

  create: async (data: TagCreateData): Promise<Tag> => {
    const response = await api.post("/api/v1/admin/tags", data);
    return response.data;
  },

  update: async (id: number, data: TagUpdateData): Promise<Tag> => {
    const response = await api.put(`/api/v1/admin/tags/${id}`, data);
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/admin/tags/${id}`);
  },
};
