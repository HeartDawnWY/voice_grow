import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2 } from "lucide-react";
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
import type { Tag } from "../../api/tags";

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
  const [editingTag, setEditingTag] = useState<Tag | null>(null);

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

  const handleEdit = (tag: Tag) => {
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

  const handleDelete = (tag: Tag) => {
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
      <div className="space-y-4">
        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Select
              options={typeFilterOptions}
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-32"
            />
          </div>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            添加标签
          </Button>
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead className="w-24">类型</TableHead>
                <TableHead className="w-24">颜色</TableHead>
                <TableHead className="w-20">排序</TableHead>
                <TableHead className="w-32">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="text-center py-8 text-gray-500"
                  >
                    加载中...
                  </TableCell>
                </TableRow>
              ) : !tags || tags.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="text-center py-8 text-gray-500"
                  >
                    暂无标签
                  </TableCell>
                </TableRow>
              ) : (
                tags.map((tag) => (
                  <TableRow key={tag.id}>
                    <TableCell className="font-mono text-gray-500">
                      {tag.id}
                    </TableCell>
                    <TableCell className="font-medium">
                      {tag.color ? (
                        <span className="inline-flex items-center gap-1">
                          <span
                            className="inline-block w-3 h-3 rounded-full"
                            style={{ backgroundColor: tag.color }}
                          />
                          {tag.name}
                        </span>
                      ) : (
                        tag.name
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {getTypeLabel(tag.type)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-gray-500 font-mono text-xs">
                      {tag.color || "-"}
                    </TableCell>
                    <TableCell className="text-gray-500">
                      {tag.sort_order ?? 0}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(tag)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(tag)}
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
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
