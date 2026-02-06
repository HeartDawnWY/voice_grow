import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, ChevronRight, FolderTree } from "lucide-react";
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
import { categoriesApi } from "../../api/categories";
import type { Category } from "../../api/categories";

const typeOptions = [
  { value: "", label: "全部类型" },
  { value: "story", label: "故事" },
  { value: "music", label: "音乐" },
  { value: "english", label: "英语" },
];

const typeFormOptions = [
  { value: "story", label: "故事" },
  { value: "music", label: "音乐" },
  { value: "english", label: "英语" },
];

const CategoryList: React.FC = () => {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("");
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    type: "story",
    parent_id: 0,
    description: "",
    icon: "",
    sort_order: 0,
  });

  const { data: categories, isLoading } = useQuery({
    queryKey: ["categories", typeFilter],
    queryFn: () => categoriesApi.list(typeFilter || undefined),
  });

  const createMutation = useMutation({
    mutationFn: categoriesApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`创建失败: ${error.message}`);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      categoriesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`更新失败: ${error.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: categoriesApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: (error: Error) => {
      alert(`删除失败: ${error.message}`);
    },
  });

  const handleCreate = (parentId?: number) => {
    setEditingCategory(null);
    setFormData({
      name: "",
      type: typeFilter || "story",
      parent_id: parentId || 0,
      description: "",
      icon: "",
      sort_order: 0,
    });
    setIsFormOpen(true);
  };

  const handleEdit = (category: Category) => {
    setEditingCategory(category);
    setFormData({
      name: category.name,
      type: category.type,
      parent_id: category.parent_id || 0,
      description: category.description || "",
      icon: category.icon || "",
      sort_order: category.sort_order || 0,
    });
    setIsFormOpen(true);
  };

  const handleFormClose = () => {
    setIsFormOpen(false);
    setEditingCategory(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingCategory) {
      updateMutation.mutate({
        id: editingCategory.id,
        data: {
          name: formData.name,
          description: formData.description,
          icon: formData.icon,
          sort_order: formData.sort_order,
        },
      });
    } else {
      createMutation.mutate({
        name: formData.name,
        type: formData.type,
        parent_id: formData.parent_id || undefined,
        description: formData.description,
        icon: formData.icon,
        sort_order: formData.sort_order,
      });
    }
  };

  const handleDelete = (category: Category) => {
    if (window.confirm(`确定要删除分类 "${category.name}" 吗？`)) {
      deleteMutation.mutate(category.id);
    }
  };

  const getTypeBadge = (type: string) => {
    switch (type) {
      case "story":
        return <Badge variant="story">故事</Badge>;
      case "music":
        return <Badge variant="music">音乐</Badge>;
      case "english":
        return <Badge variant="english">英语</Badge>;
      default:
        return <Badge variant="secondary">{type}</Badge>;
    }
  };

  // Flatten tree for table display
  const flattenCategories = (
    cats: Category[],
    depth = 0
  ): Array<Category & { _depth: number }> => {
    const result: Array<Category & { _depth: number }> = [];
    for (const cat of cats) {
      result.push({ ...cat, _depth: depth });
      if (cat.children?.length) {
        result.push(...flattenCategories(cat.children, depth + 1));
      }
    }
    return result;
  };

  const flatCategories = categories ? flattenCategories(categories) : [];

  // Build parent options for form
  const parentOptions = React.useMemo(() => {
    const options: { value: string; label: string }[] = [
      { value: "0", label: "无 (顶级分类)" },
    ];
    if (categories) {
      const flatten = (cats: Category[], prefix = "") => {
        for (const cat of cats) {
          if (!editingCategory || cat.id !== editingCategory.id) {
            options.push({
              value: String(cat.id),
              label: prefix + cat.name,
            });
          }
          if (cat.children?.length) {
            flatten(cat.children, prefix + "  ");
          }
        }
      };
      flatten(categories);
    }
    return options;
  }, [categories, editingCategory]);

  return (
    <Layout title="分类管理">
      <div className="space-y-5">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-amber-600 flex items-center justify-center shadow-lg">
              <FolderTree className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-800">分类管理</h2>
              <p className="text-gray-500 text-sm">共 {flatCategories.length} 个分类</p>
            </div>
          </div>
          <Button onClick={() => handleCreate()}>
            <Plus className="h-4 w-4 mr-2" />
            添加分类
          </Button>
        </div>

        {/* Toolbar */}
        <div className="card flex items-center gap-4 p-4">
          <Select
            options={typeOptions}
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
                <TableHead className="w-20">类型</TableHead>
                <TableHead>描述</TableHead>
                <TableHead className="w-20">排序</TableHead>
                <TableHead className="w-32 text-right">操作</TableHead>
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
              ) : flatCategories.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-14 h-14 rounded-xl bg-amber-50 flex items-center justify-center">
                        <FolderTree className="w-6 h-6 text-amber-500" />
                      </div>
                      <div>
                        <p className="text-gray-600 font-medium">暂无分类</p>
                        <p className="text-gray-400 text-sm">点击上方按钮添加第一个分类</p>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                flatCategories.map((cat) => (
                  <TableRow key={cat.id}>
                    <TableCell>
                      <span className="font-mono text-gray-400 text-xs bg-stone-100 px-2 py-1 rounded">
                        #{cat.id}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center" style={{ paddingLeft: `${cat._depth * 24}px` }}>
                        {cat._depth > 0 && (
                          <ChevronRight className="h-4 w-4 text-gray-300 mr-1" />
                        )}
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center text-white font-bold text-xs mr-2">
                          {cat.icon || cat.name[0]}
                        </div>
                        <span className="font-medium text-gray-800">{cat.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{getTypeBadge(cat.type)}</TableCell>
                    <TableCell>
                      <span className="text-gray-500 truncate block max-w-[200px]">
                        {cat.description || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500">{cat.sort_order ?? 0}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleCreate(cat.id)}
                          title="添加子分类"
                          className="hover:bg-green-50 hover:text-green-600"
                        >
                          <Plus className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(cat)}
                          className="hover:bg-orange-50 hover:text-orange-600"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(cat)}
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
            {editingCategory ? "编辑分类" : "添加分类"}
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
            {!editingCategory && (
              <Select
                label="类型"
                options={typeFormOptions}
                value={formData.type}
                onChange={(e) =>
                  setFormData({ ...formData, type: e.target.value })
                }
              />
            )}
            <Select
              label="父级分类"
              options={parentOptions}
              value={String(formData.parent_id)}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  parent_id: parseInt(e.target.value) || 0,
                })
              }
            />
            <Input
              label="描述"
              value={formData.description}
              onChange={(e) =>
                setFormData({ ...formData, description: e.target.value })
              }
            />
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="图标"
                value={formData.icon}
                onChange={(e) =>
                  setFormData({ ...formData, icon: e.target.value })
                }
                placeholder="emoji 或图标"
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

export default CategoryList;
