import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search } from "lucide-react";
import { Layout } from "../../components/layout";
import {
  Button,
  Input,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Badge,
  Pagination,
} from "../../components/ui";
import { contentsApi } from "../../api";
import type { ContentType, Content } from "../../api";
import ContentForm from "./ContentForm";

interface ContentListProps {
  type?: ContentType;
  title: string;
}

const ContentList: React.FC<ContentListProps> = ({ type, title }) => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingContent, setEditingContent] = useState<Content | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["contents", { type, page, keyword }],
    queryFn: () => contentsApi.list({ type, page, page_size: 20, keyword: keyword || undefined }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => contentsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contents"] });
    },
    onError: (error: Error) => {
      alert(`删除失败: ${error.message}`);
    },
  });

  const handleSearch = () => {
    setKeyword(searchInput);
    setPage(1);
  };

  const handleEdit = (content: Content) => {
    setEditingContent(content);
    setIsFormOpen(true);
  };

  const handleCreate = () => {
    setEditingContent(null);
    setIsFormOpen(true);
  };

  const handleDelete = (content: Content) => {
    if (window.confirm(`确定要删除 "${content.title}" 吗？`)) {
      deleteMutation.mutate(content.id);
    }
  };

  const handleFormClose = () => {
    setIsFormOpen(false);
    setEditingContent(null);
  };

  const handleFormSuccess = () => {
    handleFormClose();
    queryClient.invalidateQueries({ queryKey: ["contents"] });
  };

  const getTypeBadge = (contentType: string) => {
    switch (contentType) {
      case "story":
        return <Badge variant="default">故事</Badge>;
      case "music":
        return <Badge className="bg-purple-100 text-purple-800">音乐</Badge>;
      case "english":
        return <Badge variant="success">英语</Badge>;
      default:
        return <Badge variant="secondary">{contentType}</Badge>;
    }
  };

  return (
    <Layout title={title}>
      <div className="space-y-4">
        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索标题..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="w-64"
            />
            <Button variant="outline" onClick={handleSearch}>
              <Search className="h-4 w-4" />
            </Button>
          </div>
          <Button onClick={handleCreate}>
            <Plus className="h-4 w-4 mr-2" />
            添加内容
          </Button>
        </div>

        {/* Table */}
        <div className="rounded-lg border bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead className="w-20">类型</TableHead>
                <TableHead>标题</TableHead>
                <TableHead>分类</TableHead>
                <TableHead className="w-20">时长</TableHead>
                <TableHead className="w-20">状态</TableHead>
                <TableHead className="w-32">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-gray-500">
                    加载中...
                  </TableCell>
                </TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-gray-500">
                    暂无内容
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((content) => (
                  <TableRow key={content.id}>
                    <TableCell className="font-mono text-gray-500">{content.id}</TableCell>
                    <TableCell>{getTypeBadge(content.type)}</TableCell>
                    <TableCell className="font-medium">{content.title}</TableCell>
                    <TableCell className="text-gray-500">{content.category_name || "-"}</TableCell>
                    <TableCell className="text-gray-500">
                      {content.duration ? `${Math.floor(content.duration / 60)}:${String(content.duration % 60).padStart(2, "0")}` : "-"}
                    </TableCell>
                    <TableCell>
                      {content.is_active ? (
                        <Badge variant="success">启用</Badge>
                      ) : (
                        <Badge variant="secondary">禁用</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" onClick={() => handleEdit(content)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(content)}
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
      <ContentForm
        open={isFormOpen}
        onClose={handleFormClose}
        onSuccess={handleFormSuccess}
        content={editingContent}
        defaultType={type}
      />
    </Layout>
  );
};

export default ContentList;
