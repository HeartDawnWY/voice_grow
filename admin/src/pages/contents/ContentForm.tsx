import React, { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
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

const categoryOptions: Record<string, { value: string; label: string }[]> = {
  story: [
    { value: "", label: "选择分类" },
    { value: "bedtime", label: "睡前故事" },
    { value: "fairy_tale", label: "童话故事" },
    { value: "fable", label: "寓言故事" },
    { value: "science", label: "科普故事" },
    { value: "idiom", label: "成语故事" },
    { value: "history", label: "历史故事" },
    { value: "myth", label: "神话故事" },
  ],
  music: [
    { value: "", label: "选择分类" },
    { value: "nursery_rhyme", label: "儿歌" },
    { value: "lullaby", label: "摇篮曲" },
    { value: "classical", label: "古典音乐" },
    { value: "english", label: "英文歌" },
  ],
  english: [
    { value: "", label: "选择分类" },
    { value: "word", label: "单词" },
    { value: "sentence", label: "句子" },
    { value: "dialogue", label: "对话" },
  ],
};

const ContentForm: React.FC<ContentFormProps> = ({
  open,
  onClose,
  onSuccess,
  content,
  defaultType,
}) => {
  const isEdit = !!content;

  const [formData, setFormData] = useState({
    type: defaultType || "story",
    title: "",
    category: "",
    description: "",
    minio_path: "",
    cover_path: "",
    duration: 0,
    tags: "",
    age_min: 0,
    age_max: 12,
  });

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  useEffect(() => {
    if (content) {
      setFormData({
        type: content.type,
        title: content.title,
        category: content.category || "",
        description: content.description || "",
        minio_path: content.minio_path || "",
        cover_path: content.cover_path || "",
        duration: content.duration || 0,
        tags: content.tags || "",
        age_min: content.age_min,
        age_max: content.age_max,
      });
    } else {
      setFormData({
        type: defaultType || "story",
        title: "",
        category: "",
        description: "",
        minio_path: "",
        cover_path: "",
        duration: 0,
        tags: "",
        age_min: 0,
        age_max: 12,
      });
    }
  }, [content, defaultType, open]);

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => contentsApi.create(data),
    onSuccess: () => onSuccess(),
  });

  const updateMutation = useMutation({
    mutationFn: (data: typeof formData) => contentsApi.update(content!.id, data),
    onSuccess: () => onSuccess(),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isEdit) {
      updateMutation.mutate(formData);
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, field: "minio_path" | "cover_path") => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadProgress(0);

    try {
      const folder = field === "cover_path" ? "covers" : (formData.type as "story" | "music" | "english") === "story" ? "stories" : formData.type === "music" ? "music" : "english";
      const objectName = await uploadApi.uploadFile(file, folder as any, setUploadProgress);
      setFormData((prev) => ({ ...prev, [field]: objectName }));
    } catch (error) {
      console.error("Upload failed:", error);
      alert("上传失败，请重试");
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
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
              onChange={(e) => setFormData({ ...formData, type: e.target.value as ContentType, category: "" })}
            />
          )}

          <Input
            label="标题"
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            required
          />

          <Select
            label="分类"
            options={categoryOptions[formData.type] || [{ value: "", label: "选择分类" }]}
            value={formData.category}
            onChange={(e) => setFormData({ ...formData, category: e.target.value })}
          />

          <Textarea
            label="描述"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            rows={3}
          />

          {/* Audio Upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">音频文件</label>
            <div className="flex items-center gap-2">
              <Input
                value={formData.minio_path}
                onChange={(e) => setFormData({ ...formData, minio_path: e.target.value })}
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
            <label className="block text-sm font-medium text-gray-700 mb-1">封面图片</label>
            <div className="flex items-center gap-2">
              <Input
                value={formData.cover_path}
                onChange={(e) => setFormData({ ...formData, cover_path: e.target.value })}
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

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="时长 (秒)"
              type="number"
              value={formData.duration}
              onChange={(e) => setFormData({ ...formData, duration: parseInt(e.target.value) || 0 })}
            />
            <Input
              label="标签"
              value={formData.tags}
              onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
              placeholder="用逗号分隔"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input
              label="最小年龄"
              type="number"
              value={formData.age_min}
              onChange={(e) => setFormData({ ...formData, age_min: parseInt(e.target.value) || 0 })}
            />
            <Input
              label="最大年龄"
              type="number"
              value={formData.age_max}
              onChange={(e) => setFormData({ ...formData, age_max: parseInt(e.target.value) || 12 })}
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
