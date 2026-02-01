import { api } from "./client";

export interface Category {
  id: number;
  name: string;
  name_pinyin?: string;
  type: string;
  level: number;
  parent_id?: number;
  description?: string;
  icon?: string;
  sort_order?: number;
  is_active?: boolean;
  children?: Category[];
}

export interface CategoryCreateData {
  name: string;
  type: string;
  parent_id?: number;
  description?: string;
  icon?: string;
  sort_order?: number;
}

export interface CategoryUpdateData {
  name?: string;
  description?: string;
  icon?: string;
  sort_order?: number;
  is_active?: boolean;
}

export const categoriesApi = {
  list: async (type?: string): Promise<Category[]> => {
    const params = type ? { type } : {};
    const response = await api.get("/api/v1/admin/categories", { params });
    return response.data.categories ?? response.data;
  },

  create: async (data: CategoryCreateData): Promise<Category> => {
    const response = await api.post("/api/v1/admin/categories", data);
    return response.data;
  },

  update: async (id: number, data: CategoryUpdateData): Promise<Category> => {
    const response = await api.put(`/api/v1/admin/categories/${id}`, data);
    return response.data;
  },

  delete: async (id: number): Promise<void> => {
    await api.delete(`/api/v1/admin/categories/${id}`);
  },
};
