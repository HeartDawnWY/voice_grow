import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search, Users } from "lucide-react";
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
  Pagination,
  Dialog,
  DialogHeader,
  DialogContent,
  DialogFooter,
  Textarea,
} from "../../components/ui";
import { artistsApi } from "../../api/artists";
import type { Artist } from "../../api/artists";

const typeFilterOptions = [
  { value: "", label: "全部类型" },
  { value: "narrator", label: "讲述者" },
  { value: "singer", label: "歌手" },
  { value: "composer", label: "作曲家" },
  { value: "author", label: "作者" },
  { value: "band", label: "乐队" },
];

const typeFormOptions = [
  { value: "narrator", label: "讲述者" },
  { value: "singer", label: "歌手" },
  { value: "composer", label: "作曲家" },
  { value: "author", label: "作者" },
  { value: "band", label: "乐队" },
];

const ArtistList: React.FC = () => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingArtist, setEditingArtist] = useState<Artist | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    type: "narrator",
    avatar: "",
    description: "",
  });

  const { data, isLoading } = useQuery({
    queryKey: ["artists", { page, typeFilter, keyword }],
    queryFn: () =>
      artistsApi.list({
        page,
        page_size: 20,
        type: typeFilter || undefined,
        keyword: keyword || undefined,
      }),
  });

  const createMutation = useMutation({
    mutationFn: artistsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artists"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`创建失败: ${error.message}`);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      artistsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artists"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`更新失败: ${error.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: artistsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artists"] });
    },
    onError: (error: Error) => {
      alert(`删除失败: ${error.message}`);
    },
  });

  const handleSearch = () => {
    setKeyword(searchInput);
    setPage(1);
  };

  const handleCreate = () => {
    setEditingArtist(null);
    setFormData({
      name: "",
      type: "narrator",
      avatar: "",
      description: "",
    });
    setIsFormOpen(true);
  };

  const handleEdit = (artist: Artist) => {
    setEditingArtist(artist);
    setFormData({
      name: artist.name,
      type: artist.type,
      avatar: artist.avatar || "",
      description: artist.description || "",
    });
    setIsFormOpen(true);
  };

  const handleFormClose = () => {
    setIsFormOpen(false);
    setEditingArtist(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingArtist) {
      updateMutation.mutate({
        id: editingArtist.id,
        data: {
          name: formData.name,
          type: formData.type,
          avatar: formData.avatar,
          description: formData.description,
        },
      });
    } else {
      createMutation.mutate(formData);
    }
  };

  const handleDelete = (artist: Artist) => {
    if (window.confirm(`确定要删除艺术家 "${artist.name}" 吗？`)) {
      deleteMutation.mutate(artist.id);
    }
  };

  const getTypeBadge = (type: string) => {
    const config: Record<string, { label: string; variant: "default" | "story" | "music" | "english" | "secondary" }> = {
      narrator: { label: "讲述者", variant: "story" },
      singer: { label: "歌手", variant: "music" },
      composer: { label: "作曲家", variant: "music" },
      author: { label: "作者", variant: "english" },
      band: { label: "乐队", variant: "music" },
    };
    const { label, variant } = config[type] || { label: type, variant: "secondary" as const };
    return <Badge variant={variant}>{label}</Badge>;
  };

  return (
    <Layout title="艺术家管理">
      <div className="space-y-5">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-sky-500 to-sky-600 flex items-center justify-center shadow-lg">
              <Users className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-800">艺术家管理</h2>
              <p className="text-gray-500 text-sm">共 {data?.total ?? 0} 位艺术家</p>
            </div>
          </div>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            添加艺术家
          </Button>
        </div>

        {/* Toolbar */}
        <div className="card flex items-center gap-4 p-4">
          <div className="flex items-center gap-2 flex-1">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="搜索艺术家..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="pl-10"
              />
            </div>
            <Select
              options={typeFilterOptions}
              value={typeFilter}
              onChange={(e) => {
                setTypeFilter(e.target.value);
                setPage(1);
              }}
              className="w-32"
            />
            <Button variant="outline" onClick={handleSearch}>
              搜索
            </Button>
          </div>
        </div>

        {/* Table */}
        <div className="card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>名称</TableHead>
                <TableHead className="w-24">类型</TableHead>
                <TableHead>描述</TableHead>
                <TableHead className="w-28 text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-8 h-8 border-3 border-orange-500 border-t-transparent rounded-full animate-spin" />
                      <span className="text-gray-400">加载中...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-14 h-14 rounded-xl bg-sky-50 flex items-center justify-center">
                        <Users className="w-6 h-6 text-sky-500" />
                      </div>
                      <div>
                        <p className="text-gray-600 font-medium">暂无艺术家</p>
                        <p className="text-gray-400 text-sm">点击上方按钮添加第一位艺术家</p>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((artist) => (
                  <TableRow key={artist.id}>
                    <TableCell>
                      <span className="font-mono text-gray-400 text-xs bg-stone-100 px-2 py-1 rounded">
                        #{artist.id}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-sky-400 to-sky-500 flex items-center justify-center text-white font-bold text-sm">
                          {artist.name[0]}
                        </div>
                        <span className="font-medium text-gray-800">{artist.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>{getTypeBadge(artist.type)}</TableCell>
                    <TableCell>
                      <span className="text-gray-500 truncate block max-w-[300px]">
                        {artist.description || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(artist)}
                          className="hover:bg-orange-50 hover:text-orange-600"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(artist)}
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

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex justify-center">
            <Pagination
              page={page}
              totalPages={data.total_pages}
              onPageChange={setPage}
            />
          </div>
        )}
      </div>

      {/* Form Dialog */}
      <Dialog open={isFormOpen} onClose={handleFormClose}>
        <form onSubmit={handleSubmit}>
          <DialogHeader onClose={handleFormClose}>
            {editingArtist ? "编辑艺术家" : "添加艺术家"}
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
            <Select
              label="类型"
              options={typeFormOptions}
              value={formData.type}
              onChange={(e) =>
                setFormData({ ...formData, type: e.target.value })
              }
            />
            <Input
              label="头像 URL"
              value={formData.avatar}
              onChange={(e) =>
                setFormData({ ...formData, avatar: e.target.value })
              }
              placeholder="可选"
            />
            <Textarea
              label="描述"
              value={formData.description}
              onChange={(e) =>
                setFormData({ ...formData, description: e.target.value })
              }
              rows={3}
            />
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

export default ArtistList;
