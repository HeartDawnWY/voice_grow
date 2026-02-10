import React, { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import {
  Dialog,
  DialogHeader,
  DialogContent,
  DialogFooter,
  Button,
  Input,
  Select,
  Textarea,
} from "../../components/ui";
import { contentsApi, uploadApi } from "../../api";
import { categoriesApi } from "../../api/categories";
import { tagsApi } from "../../api/tags";
import { artistsApi } from "../../api/artists";
import type { Content, ContentType } from "../../api";

interface ContentFormProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  content: Content | null;
  defaultType?: ContentType;
}

const typeOptions = [
  { value: "story", label: "故事" },
  { value: "music", label: "音乐" },
  { value: "english", label: "英语" },
];

const ContentForm: React.FC<ContentFormProps> = ({
  open,
  onClose,
  onSuccess,
  content,
  defaultType,
}) => {
  const isEdit = !!content;

  const [formData, setFormData] = useState({
    type: defaultType || ("story" as ContentType),
    title: "",
    category_id: 0,
    description: "",
    minio_path: "",
    cover_path: "",
    duration: 0,
    tag_ids: [] as number[],
    artist_ids: [] as Array<{ id: number; role: string; is_primary: boolean }>,
    age_min: 0,
    age_max: 12,
  });

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // Dynamic category loading based on selected type
  const { data: categoriesData } = useQuery({
    queryKey: ["categories", formData.type],
    queryFn: () => categoriesApi.list(formData.type),
    enabled: open,
  });

  // Dynamic tag loading
  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => tagsApi.list(),
    enabled: open,
  });

  // Load all artists for selection
  const { data: artistsData } = useQuery({
    queryKey: ["artists-all"],
    queryFn: async () => {
      const res = await artistsApi.list({ page_size: 100 });
      return res.items;
    },
    enabled: open,
  });

  // Flatten category tree to options
  const categoryOptions = React.useMemo(() => {
    const options: { value: string; label: string }[] = [
      { value: "0", label: "选择分类" },
    ];
    const flatten = (
      cats: Array<{ id: number; name: string; children?: any[] }>,
      prefix = ""
    ) => {
      for (const cat of cats) {
        options.push({
          value: String(cat.id),
          label: prefix + cat.name,
        });
        if (cat.children?.length) {
          flatten(cat.children, prefix + "  ");
        }
      }
    };
    if (categoriesData) {
      flatten(categoriesData);
    }
    return options;
  }, [categoriesData]);

  useEffect(() => {
    if (content) {
      setFormData({
        type: content.type,
        title: content.title,
        category_id: content.category_id || 0,
        description: content.description || "",
        minio_path: content.minio_path || "",
        cover_path: content.cover_path || "",
        duration: content.duration || 0,
        tag_ids: content.tags?.map((t) => t.id) || [],
        artist_ids: content.artists?.map((a) => ({
          id: a.id,
          role: a.role,
          is_primary: a.is_primary,
        })) || [],
        age_min: content.age_min,
        age_max: content.age_max,
      });
    } else {
      setFormData({
        type: defaultType || "story",
        title: "",
        category_id: 0,
        description: "",
        minio_path: "",
        cover_path: "",
        duration: 0,
        tag_ids: [],
        artist_ids: [],
        age_min: 0,
        age_max: 12,
      });
    }
  }, [content, defaultType, open]);

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) =>
      contentsApi.create({
        type: data.type,
        title: data.title,
        category_id: data.category_id,
        description: data.description,
        minio_path: data.minio_path,
        cover_path: data.cover_path,
        duration: data.duration,
        tag_ids: data.tag_ids.length > 0 ? data.tag_ids : undefined,
        artist_ids: data.artist_ids.filter((a) => a.id > 0).length > 0
          ? data.artist_ids.filter((a) => a.id > 0)
          : undefined,
        age_min: data.age_min,
        age_max: data.age_max,
      }),
    onSuccess: () => onSuccess(),
    onError: (error: Error) => {
      alert(`创建失败: ${error.message}`);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: typeof formData) =>
      contentsApi.update(content!.id, {
        title: data.title,
        category_id: data.category_id,
        description: data.description,
        minio_path: data.minio_path,
        cover_path: data.cover_path,
        duration: data.duration,
        tag_ids: data.tag_ids,
        artist_ids: data.artist_ids.filter((a) => a.id > 0),
        age_min: data.age_min,
        age_max: data.age_max,
      }),
    onSuccess: () => onSuccess(),
    onError: (error: Error) => {
      alert(`更新失败: ${error.message}`);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isEdit) {
      updateMutation.mutate(formData);
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    field: "minio_path" | "cover_path"
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadProgress(0);

    try {
      const folder =
        field === "cover_path"
          ? "covers"
          : formData.type === "story"
            ? "stories"
            : formData.type === "music"
              ? "music"
              : "english";
      const objectName = await uploadApi.uploadFile(
        file,
        folder as any,
        setUploadProgress
      );
      setFormData((prev) => ({ ...prev, [field]: objectName }));
    } catch (error) {
      console.error("Upload failed:", error);
      alert("上传失败，请重试");
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const handleTagToggle = (tagId: number) => {
    setFormData((prev) => ({
      ...prev,
      tag_ids: prev.tag_ids.includes(tagId)
        ? prev.tag_ids.filter((id) => id !== tagId)
        : [...prev.tag_ids, tagId],
    }));
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <DialogHeader onClose={onClose}>
          {isEdit ? "编辑内容" : "添加内容"}
        </DialogHeader>

        <DialogContent className="space-y-4 max-h-[60vh] overflow-y-auto">
          {!isEdit && (
            <Select
              label="类型"
              options={typeOptions}
              value={formData.type}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  type: e.target.value as ContentType,
                  category_id: 0,
                })
              }
            />
          )}

          <Input
            label="标题"
            value={formData.title}
            onChange={(e) =>
              setFormData({ ...formData, title: e.target.value })
            }
            required
          />

          <Select
            label="分类"
            options={categoryOptions}
            value={String(formData.category_id)}
            onChange={(e) =>
              setFormData({
                ...formData,
                category_id: parseInt(e.target.value) || 0,
              })
            }
          />

          <Textarea
            label="描述"
            value={formData.description}
            onChange={(e) =>
              setFormData({ ...formData, description: e.target.value })
            }
            rows={3}
          />

          {/* Audio Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              音频文件
            </label>
            <div className="flex items-center gap-2">
              <Input
                value={formData.minio_path}
                onChange={(e) =>
                  setFormData({ ...formData, minio_path: e.target.value })
                }
                placeholder="上传或输入路径"
                className="flex-1"
              />
              <div className="relative">
                <input
                  type="file"
                  accept="audio/*"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
                  onChange={(e) => handleFileUpload(e, "minio_path")}
                  disabled={uploading}
                />
                <Button type="button" variant="outline" disabled={uploading}>
                  <Upload className="h-4 w-4 mr-1" />
                  {uploading ? `${uploadProgress}%` : "上传"}
                </Button>
              </div>
            </div>
          </div>

          {/* Cover Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              封面图片
            </label>
            <div className="flex items-center gap-2">
              <Input
                value={formData.cover_path}
                onChange={(e) =>
                  setFormData({ ...formData, cover_path: e.target.value })
                }
                placeholder="上传或输入路径"
                className="flex-1"
              />
              <div className="relative">
                <input
                  type="file"
                  accept="image/*"
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
                  onChange={(e) => handleFileUpload(e, "cover_path")}
                  disabled={uploading}
                />
                <Button type="button" variant="outline" disabled={uploading}>
                  <Upload className="h-4 w-4 mr-1" />
                  上传
                </Button>
              </div>
            </div>
          </div>

          <Input
            label="时长 (秒)"
            type="number"
            value={formData.duration}
            onChange={(e) =>
              setFormData({
                ...formData,
                duration: parseInt(e.target.value) || 0,
              })
            }
          />

          {/* Tags */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              标签
            </label>
            <div className="flex flex-wrap gap-2">
              {tagsData?.map((tag) => (
                <label
                  key={tag.id}
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs cursor-pointer border transition-colors ${
                    formData.tag_ids.includes(tag.id)
                      ? "bg-primary-100 border-primary-500 text-primary-700"
                      : "bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={formData.tag_ids.includes(tag.id)}
                    onChange={() => handleTagToggle(tag.id)}
                  />
                  {tag.name}
                </label>
              ))}
              {(!tagsData || tagsData.length === 0) && (
                <span className="text-xs text-gray-400">暂无标签</span>
              )}
            </div>
          </div>

          {/* Artists */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              艺术家
            </label>
            {formData.artist_ids.map((entry, idx) => (
              <div key={idx} className="flex items-center gap-2 mb-2">
                <select
                  className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm"
                  value={entry.id}
                  onChange={(e) => {
                    const next = [...formData.artist_ids];
                    next[idx] = { ...next[idx], id: parseInt(e.target.value) };
                    setFormData({ ...formData, artist_ids: next });
                  }}
                >
                  <option value={0}>选择艺术家</option>
                  {artistsData?.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                <select
                  className="w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  value={entry.role}
                  onChange={(e) => {
                    const next = [...formData.artist_ids];
                    next[idx] = { ...next[idx], role: e.target.value };
                    setFormData({ ...formData, artist_ids: next });
                  }}
                >
                  <option value="singer">歌手</option>
                  <option value="author">作者</option>
                  <option value="narrator">讲述者</option>
                  <option value="composer">作曲</option>
                  <option value="lyricist">作词</option>
                </select>
                <label className="flex items-center gap-1 text-xs text-gray-500 whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={entry.is_primary}
                    onChange={(e) => {
                      const next = [...formData.artist_ids];
                      next[idx] = { ...next[idx], is_primary: e.target.checked };
                      setFormData({ ...formData, artist_ids: next });
                    }}
                  />
                  主要
                </label>
                <button
                  type="button"
                  className="text-red-400 hover:text-red-600 text-sm px-1"
                  onClick={() => {
                    setFormData({
                      ...formData,
                      artist_ids: formData.artist_ids.filter((_, i) => i !== idx),
                    });
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setFormData({
                  ...formData,
                  artist_ids: [
                    ...formData.artist_ids,
                    { id: 0, role: "singer", is_primary: formData.artist_ids.length === 0 },
                  ],
                })
              }
            >
              + 添加艺术家
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="最小年龄"
              type="number"
              value={formData.age_min}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  age_min: parseInt(e.target.value) || 0,
                })
              }
            />
            <Input
              label="最大年龄"
              type="number"
              value={formData.age_max}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  age_max: parseInt(e.target.value) || 12,
                })
              }
            />
          </div>
        </DialogContent>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? "保存中..." : "保存"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
};

export default ContentForm;
