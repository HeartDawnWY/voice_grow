import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search } from "lucide-react";
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
    const labels: Record<string, string> = {
      narrator: "讲述者",
      singer: "歌手",
      composer: "作曲家",
      author: "作者",
      band: "乐队",
    };
    return <Badge variant="secondary">{labels[type] || type}</Badge>;
  };

  return (
    <Layout title="艺术家管理">
      <div className="space-y-4">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="搜索艺术家..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="w-48"
            />
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
              <Search className="h-4 w-4" />
            </Button>
          </div>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            添加艺术家
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
                <TableHead>描述</TableHead>
                <TableHead className="w-32">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center py-8 text-gray-500"
                  >
                    加载中...
                  </TableCell>
                </TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center py-8 text-gray-500"
                  >
                    暂无艺术家
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((artist) => (
                  <TableRow key={artist.id}>
                    <TableCell className="font-mono text-gray-500">
                      {artist.id}
                    </TableCell>
                    <TableCell className="font-medium">{artist.name}</TableCell>
                    <TableCell>{getTypeBadge(artist.type)}</TableCell>
                    <TableCell className="text-gray-500 truncate max-w-[300px]">
                      {artist.description || "-"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(artist)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(artist)}
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
