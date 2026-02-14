import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search, BookOpen, Music, Languages, Filter, X, Upload } from "lucide-react";
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
} from "../../components/ui";
import { contentsApi, categoriesApi, artistsApi } from "../../api";
import type { ContentType, Content } from "../../api";
import ContentForm from "./ContentForm";
import BatchUploadForm from "./BatchUploadForm";

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
  const [isBatchOpen, setIsBatchOpen] = useState(false);
  const [editingContent, setEditingContent] = useState<Content | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [categoryId, setCategoryId] = useState<number | undefined>();
  const [artistId, setArtistId] = useState<number | undefined>();
  const [isActive, setIsActive] = useState<boolean | undefined>();

  const activeFilterCount = [categoryId, artistId, isActive].filter(v => v !== undefined).length;

  const { data, isLoading } = useQuery({
    queryKey: ["contents", { type, page, keyword, categoryId, artistId, isActive }],
    queryFn: () => contentsApi.list({
      type, page, page_size: 20,
      keyword: keyword || undefined,
      category_id: categoryId,
      artist_id: artistId,
      is_active: isActive,
    }),
  });

  const { data: categories } = useQuery({
    queryKey: ["categories", type],
    queryFn: () => categoriesApi.list(type),
    enabled: showFilters,
  });

  const categoryOptions = useMemo(() => {
    const options: { value: string; label: string }[] = [
      { value: "", label: "全部分类" },
    ];
    const flatten = (
      cats: Array<{ id: number; name: string; children?: any[] }>,
      prefix = ""
    ) => {
      for (const cat of cats) {
        options.push({ value: String(cat.id), label: prefix + cat.name });
        if (cat.children?.length) {
          flatten(cat.children, prefix + "  ");
        }
      }
    };
    if (categories) flatten(categories);
    return options;
  }, [categories]);

  const { data: artists } = useQuery({
    queryKey: ["artists-all-filter"],
    queryFn: async () => {
      const res = await artistsApi.list({ page_size: 100 });
      return res.items;
    },
    enabled: showFilters,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => contentsApi.delete(id, true),
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

  const handleResetFilters = () => {
    setCategoryId(undefined);
    setArtistId(undefined);
    setIsActive(undefined);
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
        return <Badge variant="story">故事</Badge>;
      case "music":
        return <Badge variant="music">音乐</Badge>;
      case "english":
        return <Badge variant="english">英语</Badge>;
      default:
        return <Badge variant="secondary">{contentType}</Badge>;
    }
  };

  const getTypeIcon = () => {
    switch (type) {
      case "story":
        return <BookOpen className="w-6 h-6 text-rose-500" />;
      case "music":
        return <Music className="w-6 h-6 text-violet-500" />;
      default:
        return <Languages className="w-6 h-6 text-emerald-500" />;
    }
  };

  const getTypeColor = () => {
    switch (type) {
      case "story":
        return "from-rose-500 to-rose-600";
      case "music":
        return "from-violet-500 to-violet-600";
      default:
        return "from-emerald-500 to-emerald-600";
    }
  };

  const getIconBg = () => {
    switch (type) {
      case "story":
        return "bg-rose-50";
      case "music":
        return "bg-violet-50";
      default:
        return "bg-emerald-50";
    }
  };

  return (
    <Layout title={title}>
      <div className="space-y-5">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${getTypeColor()} flex items-center justify-center shadow-lg`}>
              {type === "story" ? <BookOpen className="w-6 h-6 text-white" /> :
               type === "music" ? <Music className="w-6 h-6 text-white" /> :
               <Languages className="w-6 h-6 text-white" />}
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-800">{title}</h2>
              <p className="text-gray-500 text-sm">共 {data?.total ?? 0} 条内容</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setIsBatchOpen(true)}>
              <Upload className="h-4 w-4 mr-2" />
              批量添加
            </Button>
            <Button onClick={handleCreate} className={`bg-gradient-to-r ${getTypeColor()} text-white shadow-lg`}>
              <Plus className="h-4 w-4 mr-2" />
              添加内容
            </Button>
          </div>
        </div>

        {/* Toolbar */}
        <div className="card flex items-center gap-4 p-4">
          <div className="flex items-center gap-2 flex-1">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="搜索标题..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="pl-10"
              />
            </div>
            <Button variant="outline" onClick={handleSearch}>
              搜索
            </Button>
          </div>
          <Button
            variant={activeFilterCount > 0 ? "outline" : "ghost"}
            size="icon"
            onClick={() => setShowFilters(!showFilters)}
            className={activeFilterCount > 0 ? "border-orange-300 text-orange-600 bg-orange-50" : ""}
          >
            <Filter className="h-4 w-4" />
            {activeFilterCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-orange-500 text-white text-[10px] rounded-full flex items-center justify-center">
                {activeFilterCount}
              </span>
            )}
          </Button>
        </div>

        {/* Filter Panel */}
        {showFilters && (
          <div className="card px-4 py-3 flex items-center gap-3 flex-wrap">
            <span className="text-xs font-medium text-gray-400 uppercase tracking-wider mr-1">筛选</span>
            <div className="w-[180px]">
              <Select
                variant="filter"
                label="分类"
                value={categoryId?.toString() ?? ""}
                onChange={(e) => {
                  setCategoryId(e.target.value ? Number(e.target.value) : undefined);
                  setPage(1);
                }}
                options={categoryOptions}
              />
            </div>
            <div className="w-[180px]">
              <Select
                variant="filter"
                label="艺术家"
                value={artistId?.toString() ?? ""}
                onChange={(e) => {
                  setArtistId(e.target.value ? Number(e.target.value) : undefined);
                  setPage(1);
                }}
                options={[
                  { value: "", label: "全部" },
                  ...(artists?.map(a => ({ value: a.id.toString(), label: a.name })) ?? []),
                ]}
              />
            </div>
            <div className="w-[140px]">
              <Select
                variant="filter"
                label="状态"
                value={isActive === undefined ? "" : isActive ? "true" : "false"}
                onChange={(e) => {
                  setIsActive(e.target.value === "" ? undefined : e.target.value === "true");
                  setPage(1);
                }}
                options={[
                  { value: "", label: "全部" },
                  { value: "true", label: "启用" },
                  { value: "false", label: "禁用" },
                ]}
              />
            </div>
            {activeFilterCount > 0 && (
              <button
                onClick={handleResetFilters}
                className="ml-auto text-xs text-gray-400 hover:text-red-500 transition-colors flex items-center gap-1"
              >
                <X className="h-3 w-3" />
                清除
              </button>
            )}
          </div>
        )}

        {/* Table */}
        <div className="card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                {!type && <TableHead className="w-24">类型</TableHead>}
                <TableHead>标题</TableHead>
                <TableHead>分类</TableHead>
                <TableHead>艺术家</TableHead>
                <TableHead className="w-24">时长</TableHead>
                <TableHead className="w-24">状态</TableHead>
                <TableHead className="w-32 text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={type ? 7 : 8} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-8 h-8 border-3 border-orange-500 border-t-transparent rounded-full animate-spin" />
                      <span className="text-gray-400">加载中...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={type ? 7 : 8} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className={`w-14 h-14 rounded-xl ${getIconBg()} flex items-center justify-center`}>
                        {getTypeIcon()}
                      </div>
                      <div>
                        <p className="text-gray-600 font-medium">暂无内容</p>
                        <p className="text-gray-400 text-sm">点击上方按钮添加第一条内容</p>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((content) => (
                  <TableRow key={content.id} className="table-row">
                    <TableCell>
                      <span className="font-mono text-gray-400 text-xs bg-stone-100 px-2 py-1 rounded">
                        #{content.id}
                      </span>
                    </TableCell>
                    {!type && <TableCell>{getTypeBadge(content.type)}</TableCell>}
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm ${
                          content.type === "story" ? "bg-gradient-to-br from-rose-400 to-rose-500" :
                          content.type === "music" ? "bg-gradient-to-br from-violet-400 to-violet-500" :
                          "bg-gradient-to-br from-emerald-400 to-emerald-500"
                        }`}>
                          {content.title[0]}
                        </div>
                        <div>
                          <p className="font-medium text-gray-800">{content.title}</p>
                          {content.subtitle && (
                            <p className="text-xs text-gray-400">{content.subtitle}</p>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500">{content.category_name || "-"}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500 text-sm">
                        {content.artists && content.artists.length > 0
                          ? content.artists.map(a => a.name).join(", ")
                          : "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500 font-mono text-sm">
                        {content.duration
                          ? `${Math.floor(content.duration / 60)}:${String(content.duration % 60).padStart(2, "0")}`
                          : "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      {content.is_active ? (
                        <Badge variant="success">启用</Badge>
                      ) : (
                        <Badge variant="secondary">禁用</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(content)}
                          className="hover:bg-orange-50 hover:text-orange-600"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(content)}
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
      <ContentForm
        open={isFormOpen}
        onClose={handleFormClose}
        onSuccess={handleFormSuccess}
        content={editingContent}
        defaultType={type}
      />

      {/* Batch Upload Dialog */}
      <BatchUploadForm
        open={isBatchOpen}
        onClose={() => setIsBatchOpen(false)}
        onSuccess={() => {
          setIsBatchOpen(false);
          queryClient.invalidateQueries({ queryKey: ["contents"] });
        }}
        defaultType={type}
      />
    </Layout>
  );
};

export default ContentList;
