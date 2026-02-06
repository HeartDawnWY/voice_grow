import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Tag } from "lucide-react";
import { Layout } from "../../components/layout";
import {
  Button,
  Input,
  Select,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Badge,
  Dialog,
  DialogHeader,
  DialogContent,
  DialogFooter,
} from "../../components/ui";
import { tagsApi } from "../../api/tags";
import type { Tag as TagType } from "../../api/tags";

const typeFilterOptions = [
  { value: "", label: "全部类型" },
  { value: "theme", label: "主题" },
  { value: "mood", label: "情绪" },
  { value: "age", label: "年龄" },
  { value: "scene", label: "场景" },
  { value: "feature", label: "特性" },
];

const typeFormOptions = [
  { value: "theme", label: "主题" },
  { value: "mood", label: "情绪" },
  { value: "age", label: "年龄" },
  { value: "scene", label: "场景" },
  { value: "feature", label: "特性" },
];

const TagList: React.FC = () => {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("");
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingTag, setEditingTag] = useState<TagType | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    type: "theme",
    color: "",
    sort_order: 0,
  });

  const { data: tags, isLoading } = useQuery({
    queryKey: ["tags", typeFilter],
    queryFn: () => tagsApi.list(typeFilter || undefined),
  });

  const createMutation = useMutation({
    mutationFn: tagsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`创建失败: ${error.message}`);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      tagsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`更新失败: ${error.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: tagsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
    onError: (error: Error) => {
      alert(`删除失败: ${error.message}`);
    },
  });

  const handleCreate = () => {
    setEditingTag(null);
    setFormData({
      name: "",
      type: typeFilter || "theme",
      color: "",
      sort_order: 0,
    });
    setIsFormOpen(true);
  };

  const handleEdit = (tag: TagType) => {
    setEditingTag(tag);
    setFormData({
      name: tag.name,
      type: tag.type,
      color: tag.color || "",
      sort_order: tag.sort_order || 0,
    });
    setIsFormOpen(true);
  };

  const handleFormClose = () => {
    setIsFormOpen(false);
    setEditingTag(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingTag) {
      updateMutation.mutate({
        id: editingTag.id,
        data: {
          name: formData.name,
          color: formData.color,
          sort_order: formData.sort_order,
        },
      });
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleDelete = (tag: TagType) => {
    if (window.confirm(`确定要删除标签 "${tag.name}" 吗？`)) {
      deleteMutation.mutate(tag.id);
    }
  };

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      theme: "主题",
      mood: "情绪",
      age: "年龄",
      scene: "场景",
      feature: "特性",
    };
    return labels[type] || type;
  };

  return (
    <Layout title="标签管理">
      <div className="space-y-5">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-teal-500 to-teal-600 flex items-center justify-center shadow-lg">
              <Tag className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-800">标签管理</h2>
              <p className="text-gray-500 text-sm">共 {tags?.length ?? 0} 个标签</p>
            </div>
          </div>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            添加标签
          </Button>
        </div>

        {/* Toolbar */}
        <div className="card flex items-center gap-4 p-4">
          <Select
            options={typeFilterOptions}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="w-32"
          />
        </div>

        {/* Table */}
        <div className="card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead className="w-24">类型</TableHead>
                <TableHead className="w-24">颜色</TableHead>
                <TableHead className="w-20">排序</TableHead>
                <TableHead className="w-28 text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-8 h-8 border-3 border-orange-500 border-t-transparent rounded-full animate-spin" />
                      <span className="text-gray-400">加载中...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : !tags || tags.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-14 h-14 rounded-xl bg-teal-50 flex items-center justify-center">
                        <Tag className="w-6 h-6 text-teal-500" />
                      </div>
                      <div>
                        <p className="text-gray-600 font-medium">暂无标签</p>
                        <p className="text-gray-400 text-sm">点击上方按钮添加第一个标签</p>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                tags.map((tag) => (
                  <TableRow key={tag.id}>
                    <TableCell>
                      <span className="font-mono text-gray-400 text-xs bg-stone-100 px-2 py-1 rounded">
                        #{tag.id}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {tag.color && (
                          <span
                            className="w-3 h-3 rounded-full ring-2 ring-white shadow"
                            style={{ backgroundColor: tag.color }}
                          />
                        )}
                        <span className="font-medium text-gray-800">{tag.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{getTypeLabel(tag.type)}</Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500 font-mono text-xs">
                        {tag.color || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500">{tag.sort_order ?? 0}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(tag)}
                          className="hover:bg-orange-50 hover:text-orange-600"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(tag)}
                          disabled={deleteMutation.isPending}
                          className="hover:bg-red-50 hover:text-red-500"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Form Dialog */}
      <Dialog open={isFormOpen} onClose={handleFormClose}>
        <form onSubmit={handleSubmit}>
          <DialogHeader onClose={handleFormClose}>
            {editingTag ? "编辑标签" : "添加标签"}
          </DialogHeader>
          <DialogContent className="space-y-4">
            <Input
              label="名称"
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              required
            />
            {!editingTag && (
              <Select
                label="类型"
                options={typeFormOptions}
                value={formData.type}
                onChange={(e) =>
                  setFormData({ ...formData, type: e.target.value })
                }
              />
            )}
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="颜色"
                value={formData.color}
                onChange={(e) =>
                  setFormData({ ...formData, color: e.target.value })
                }
                placeholder="#FF5733"
              />
              <Input
                label="排序"
                type="number"
                value={formData.sort_order}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    sort_order: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
          </DialogContent>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleFormClose}>
              取消
            </Button>
            <Button
              type="submit"
              disabled={createMutation.isPending || updateMutation.isPending}
            >
              {createMutation.isPending || updateMutation.isPending
                ? "保存中..."
                : "保存"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </Layout>
  );
};

export default TagList;
