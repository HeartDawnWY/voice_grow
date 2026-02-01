import { api } from "./client";

export interface Stats {
  connected_devices: number;
  version: string;
  total_contents: number;
  story_count: number;
  music_count: number;
  english_count: number;
  word_count: number;
}

export const statsApi = {
  get: async (): Promise<Stats> => {
    const response = await api.get("/api/v1/stats");
    return response.data;
  },
};
