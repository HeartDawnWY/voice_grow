import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Link,
  X,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Search,
  ExternalLink,
  AlertCircle,
} from "lucide-react";
import { Layout } from "../../components/layout";
import {
  Button,
  Input,
  Select,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../components/ui";
import {
  youtubeApi,
  downloadApi,
  categoriesApi,
  artistsApi,
  type SearchResultItem,
} from "../../api";

type PageMode = "search" | "url";

const contentTypeOptions = [
  { value: "music", label: "音乐" },
  { value: "story", label: "故事" },
];

const artistTypeOptions = [
  { value: "singer", label: "歌手" },
  { value: "band", label: "乐队" },
  { value: "narrator", label: "讲述者" },
  { value: "author", label: "作者" },
  { value: "composer", label: "作曲家" },
];

const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];

const statusConfig: Record<
  string,
  { label: string; variant: "default" | "success" | "destructive" | "warning" | "secondary" }
> = {
  pending: { label: "等待中", variant: "secondary" },
  extracting_info: { label: "解析中", variant: "default" },
  downloading: { label: "下载中", variant: "default" },
  uploading: { label: "上传中", variant: "default" },
  creating_record: { label: "创建记录", variant: "default" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
  cancelled: { label: "已取消", variant: "warning" },
};

const trackStatusConfig: Record<string, { icon: React.ElementType; color: string }> = {
  pending: { icon: Clock, color: "text-gray-400" },
  downloading: { icon: Loader2, color: "text-blue-500" },
  uploading: { icon: Loader2, color: "text-orange-500" },
  creating_record: { icon: Loader2, color: "text-violet-500" },
  completed: { icon: CheckCircle2, color: "text-green-500" },
  failed: { icon: XCircle, color: "text-red-500" },
};

const PLATFORM_COLORS: Record<string, string> = {
  youtube: "bg-red-100 text-red-700",
  bilibili: "bg-blue-100 text-blue-700",
  soundcloud: "bg-orange-100 text-orange-700",
  niconico: "bg-pink-100 text-pink-700",
};

function formatDuration(seconds: number): string {
  if (!seconds) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatCount(n: number): string {
  if (!n) return "0";
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

const YouTubeDownload: React.FC = () => {
  const queryClient = useQueryClient();

  // Mode
  const [mode, setMode] = useState<PageMode>("search");

  // ========== 共享状态 ==========
  const [contentType, setContentType] = useState("music");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [artistId, setArtistId] = useState<string>("");
  const [artistType, setArtistType] = useState("singer");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  // ========== 搜索模式状态 ==========
  const [keyword, setKeyword] = useState("");
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([
    "youtube",
    "bilibili",
    "soundcloud",
  ]);
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([]);
  const [searchMeta, setSearchMeta] = useState<{
    total_count: number;
    dedup_removed_count: number;
    platforms_searched: string[];
  } | null>(null);
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());

  // ========== URL 模式状态 ==========
  const [url, setUrl] = useState("");

  // ========== 数据查询 ==========
  const categoryType = contentType === "story" ? "story" : "music";
  const { data: categories = [] } = useQuery({
    queryKey: ["categories", categoryType],
    queryFn: () => categoriesApi.list(categoryType),
  });

  const { data: artistsData } = useQuery({
    queryKey: ["artists", { page_size: 100 }],
    queryFn: () => artistsApi.list({ page_size: 100 }),
  });

  const { data: platforms = [] } = useQuery({
    queryKey: ["download-platforms"],
    queryFn: () => downloadApi.getPlatforms(),
  });

  const artistOptions = React.useMemo(() => {
    const result: { value: string; label: string }[] = [
      { value: "", label: "自动识别" },
    ];
    if (artistsData?.items) {
      const typeLabels: Record<string, string> = {
        singer: "歌手",
        band: "乐队",
        narrator: "讲述者",
        author: "作者",
        composer: "作曲家",
      };
      for (const a of artistsData.items) {
        const typeLabel = typeLabels[a.type] || a.type;
        result.push({ value: String(a.id), label: `${a.name} (${typeLabel})` });
      }
    }
    return result;
  }, [artistsData]);

  const flatCategories = React.useMemo(() => {
    const result: { value: string; label: string }[] = [
      { value: "", label: "请选择分类" },
    ];
    const flatten = (cats: typeof categories, prefix = "") => {
      for (const cat of cats) {
        result.push({
          value: String(cat.id),
          label: prefix ? `${prefix} / ${cat.name}` : cat.name,
        });
        if (cat.children?.length) {
          flatten(cat.children, prefix ? `${prefix} / ${cat.name}` : cat.name);
        }
      }
    };
    flatten(categories);
    return result;
  }, [categories]);

  // ========== 轮询任务 ==========
  const { data: activeTask } = useQuery({
    queryKey: ["download-task", activeTaskId],
    queryFn: () => youtubeApi.getTask(activeTaskId!),
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const task = query.state.data;
      if (!task || TERMINAL_STATUSES.includes(task.status)) return false;
      return 2500;
    },
  });

  const { data: taskList = [] } = useQuery({
    queryKey: ["download-tasks"],
    queryFn: () => youtubeApi.listTasks(),
    refetchInterval: 10000,
  });

  // ========== Mutations ==========

  // 搜索
  const searchMutation = useMutation({
    mutationFn: downloadApi.search,
    onSuccess: (data) => {
      setSearchResults(data.results);
      setSearchMeta({
        total_count: data.total_count,
        dedup_removed_count: data.dedup_removed_count,
        platforms_searched: data.platforms_searched,
      });
      setSelectedUrls(new Set());
    },
    onError: (error: Error) => {
      alert(`搜索失败: ${error.message}`);
    },
  });

  // 批量下载
  const batchDownloadMutation = useMutation({
    mutationFn: downloadApi.batchDownload,
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      setSelectedUrls(new Set());
      queryClient.invalidateQueries({ queryKey: ["download-tasks"] });
    },
    onError: (error: Error) => {
      alert(`下载失败: ${error.message}`);
    },
  });

  // URL 下载
  const downloadMutation = useMutation({
    mutationFn: youtubeApi.startDownload,
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["download-tasks"] });
    },
    onError: (error: Error) => {
      alert(`下载失败: ${error.message}`);
    },
  });

  // 取消
  const cancelMutation = useMutation({
    mutationFn: youtubeApi.cancelTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["download-task", activeTaskId] });
      queryClient.invalidateQueries({ queryKey: ["download-tasks"] });
    },
  });

  useEffect(() => {
    if (activeTask && TERMINAL_STATUSES.includes(activeTask.status)) {
      queryClient.invalidateQueries({ queryKey: ["download-tasks"] });
    }
  }, [activeTask?.status, queryClient]);

  const selectedArtist = React.useMemo(() => {
    if (!artistId || !artistsData?.items) return null;
    return artistsData.items.find((a) => String(a.id) === artistId) ?? null;
  }, [artistId, artistsData]);

  // ========== 搜索操作 ==========

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyword.trim()) return;
    searchMutation.mutate({
      keyword: keyword.trim(),
      platforms: selectedPlatforms,
      content_type: contentType,
      max_results: 10,
    });
  };

  const togglePlatform = (platformId: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(platformId)
        ? prev.filter((p) => p !== platformId)
        : [...prev, platformId]
    );
  };

  const toggleSelectUrl = (itemUrl: string) => {
    setSelectedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(itemUrl)) next.delete(itemUrl);
      else next.add(itemUrl);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const downloadable = searchResults.filter((r) => !r.exists_in_db);
    if (selectedUrls.size === downloadable.length) {
      setSelectedUrls(new Set());
    } else {
      setSelectedUrls(new Set(downloadable.map((r) => r.url)));
    }
  };

  const handleBatchDownload = () => {
    if (selectedUrls.size === 0 || categoryId === "") return;
    batchDownloadMutation.mutate({
      urls: Array.from(selectedUrls),
      content_type: contentType,
      category_id: Number(categoryId),
      artist_name: selectedArtist?.name ?? undefined,
      artist_type: selectedArtist?.type ?? artistType,
    });
  };

  // ========== URL 下载操作 ==========

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || categoryId === "") return;
    downloadMutation.mutate({
      url: url.trim(),
      content_type: contentType,
      category_id: Number(categoryId),
      artist_name: selectedArtist?.name ?? undefined,
      artist_type: selectedArtist?.type ?? artistType,
    });
  };

  const isActiveRunning =
    activeTask && !TERMINAL_STATUSES.includes(activeTask.status);
  const progressPercent =
    activeTask && activeTask.total_count > 0
      ? Math.round(
          ((activeTask.completed_count + activeTask.failed_count) /
            activeTask.total_count) *
            100
        )
      : 0;
  const historyTasks = taskList.filter((t) => t.task_id !== activeTaskId);

  return (
    <Layout title="内容采集">
      <div className="space-y-6">
        {/* Page header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-200">
            <Search className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-800">内容采集</h2>
            <p className="text-sm text-gray-500">
              搜索或下载多平台音视频，自动转码并创建内容记录
            </p>
          </div>
        </div>

        {/* Mode switch */}
        <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
          <button
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              mode === "search"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
            onClick={() => setMode("search")}
          >
            <Search className="h-4 w-4 inline mr-1.5 -mt-0.5" />
            关键字搜索
          </button>
          <button
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              mode === "url"
                ? "bg-white text-gray-800 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
            onClick={() => setMode("url")}
          >
            <Link className="h-4 w-4 inline mr-1.5 -mt-0.5" />
            URL 下载
          </button>
        </div>

        {/* ========== 搜索模式 ========== */}
        {mode === "search" && (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">搜索</CardTitle>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleSearch} className="space-y-4">
                  {/* Keyword input */}
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <Input
                      className="pl-10"
                      placeholder="输入搜索关键字..."
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                    />
                  </div>

                  {/* Platform checkboxes */}
                  <div className="flex items-center gap-4 flex-wrap">
                    <span className="text-sm text-gray-500">搜索平台:</span>
                    {platforms.map((p) => (
                      <label
                        key={p.id}
                        className="flex items-center gap-1.5 cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedPlatforms.includes(p.id)}
                          onChange={() => togglePlatform(p.id)}
                          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        <span className="text-sm text-gray-700">{p.label}</span>
                      </label>
                    ))}
                  </div>

                  {/* Content type + category */}
                  <div className="grid grid-cols-2 gap-3">
                    <Select
                      label="内容类型"
                      options={contentTypeOptions}
                      value={contentType}
                      onChange={(e) => {
                        setContentType(e.target.value);
                        setCategoryId("");
                      }}
                    />
                    <Select
                      label="分类"
                      options={flatCategories}
                      value={String(categoryId)}
                      onChange={(e) =>
                        setCategoryId(e.target.value ? Number(e.target.value) : "")
                      }
                    />
                  </div>

                  <div className="flex justify-end">
                    <Button
                      type="submit"
                      disabled={
                        !keyword.trim() ||
                        selectedPlatforms.length === 0 ||
                        searchMutation.isPending
                      }
                      className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-md"
                    >
                      {searchMutation.isPending ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Search className="h-4 w-4 mr-2" />
                      )}
                      搜索
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>

            {/* Search results */}
            {searchResults.length > 0 && (
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <CardTitle className="text-base">
                        搜索结果 ({searchMeta?.total_count ?? 0} 条
                        {searchMeta && searchMeta.dedup_removed_count > 0 && (
                          <span className="text-gray-400 font-normal">
                            , 去重 {searchMeta.dedup_removed_count} 条
                          </span>
                        )}
                        )
                      </CardTitle>
                    </div>
                    <div className="flex items-center gap-3">
                      {selectedUrls.size > 0 && (
                        <>
                          {/* Artist + type selectors for batch download */}
                          <div className="flex items-center gap-2">
                            <Select
                              label=""
                              options={artistOptions}
                              value={artistId}
                              onChange={(e) => setArtistId(e.target.value)}
                            />
                            {!artistId && (
                              <Select
                                label=""
                                options={artistTypeOptions}
                                value={artistType}
                                onChange={(e) => setArtistType(e.target.value)}
                              />
                            )}
                          </div>
                        </>
                      )}
                      <Button
                        onClick={handleBatchDownload}
                        disabled={
                          selectedUrls.size === 0 ||
                          categoryId === "" ||
                          batchDownloadMutation.isPending ||
                          !!isActiveRunning
                        }
                        className="bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-600 hover:to-emerald-700 text-white shadow-md"
                      >
                        {batchDownloadMutation.isPending ? (
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                          <Download className="h-4 w-4 mr-2" />
                        )}
                        下载选中 ({selectedUrls.size})
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {/* Select all */}
                  <div className="flex items-center gap-2 mb-3 pb-2 border-b">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={
                          selectedUrls.size > 0 &&
                          selectedUrls.size ===
                            searchResults.filter((r) => !r.exists_in_db).length
                        }
                        onChange={toggleSelectAll}
                        className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="text-sm text-gray-600">全选</span>
                    </label>
                    {categoryId === "" && selectedUrls.size > 0 && (
                      <span className="text-xs text-amber-600 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        请先选择分类
                      </span>
                    )}
                  </div>

                  {/* Result list */}
                  <div className="space-y-2 max-h-[600px] overflow-y-auto">
                    {searchResults.map((item, idx) => (
                      <div
                        key={`${item.platform}-${item.url}-${idx}`}
                        className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${
                          item.exists_in_db
                            ? "bg-gray-50 border-gray-200 opacity-70"
                            : selectedUrls.has(item.url)
                            ? "bg-indigo-50 border-indigo-200"
                            : "bg-white border-gray-100 hover:border-gray-200"
                        }`}
                      >
                        {/* Checkbox */}
                        <input
                          type="checkbox"
                          checked={selectedUrls.has(item.url)}
                          onChange={() => toggleSelectUrl(item.url)}
                          disabled={item.exists_in_db}
                          className="mt-1 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
                        />

                        {/* Thumbnail */}
                        {item.thumbnail ? (
                          <img
                            src={item.thumbnail}
                            alt=""
                            className="w-20 h-14 object-cover rounded flex-shrink-0"
                            onError={(e) => {
                              (e.target as HTMLImageElement).style.display = "none";
                            }}
                          />
                        ) : (
                          <div className="w-20 h-14 bg-gray-100 rounded flex-shrink-0 flex items-center justify-center">
                            <Search className="h-5 w-5 text-gray-300" />
                          </div>
                        )}

                        {/* Info */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start gap-2">
                            <span className="text-sm font-medium text-gray-800 truncate flex-1">
                              {item.title}
                            </span>
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          </div>
                          <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                            <span
                              className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                                PLATFORM_COLORS[item.platform] ?? "bg-gray-100 text-gray-600"
                              }`}
                            >
                              {item.platform}
                            </span>
                            <span>{formatDuration(item.duration)}</span>
                            <span>{formatCount(item.view_count)} 播放</span>
                            {item.uploader && (
                              <span className="truncate max-w-32">{item.uploader}</span>
                            )}
                            <span className="ml-auto font-medium text-indigo-600">
                              {item.quality_score}分
                            </span>
                            {item.exists_in_db && (
                              <Badge variant="warning">已存在</Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Empty state after search */}
            {searchMeta && searchResults.length === 0 && (
              <Card>
                <CardContent className="py-12 text-center">
                  <Search className="h-10 w-10 text-gray-300 mx-auto mb-3" />
                  <p className="text-gray-500">未找到相关内容</p>
                </CardContent>
              </Card>
            )}
          </>
        )}

        {/* ========== URL 模式 ========== */}
        {mode === "url" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">URL 下载</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleUrlSubmit} className="space-y-4">
                <div className="relative">
                  <Link className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                  <Input
                    className="pl-10"
                    placeholder="输入视频或播放列表 URL"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                  />
                </div>

                <div
                  className={`grid grid-cols-2 ${
                    !artistId ? "md:grid-cols-4" : "md:grid-cols-3"
                  } gap-3`}
                >
                  <Select
                    label="内容类型"
                    options={contentTypeOptions}
                    value={contentType}
                    onChange={(e) => {
                      setContentType(e.target.value);
                      setCategoryId("");
                    }}
                  />
                  <Select
                    label="分类"
                    options={flatCategories}
                    value={String(categoryId)}
                    onChange={(e) =>
                      setCategoryId(e.target.value ? Number(e.target.value) : "")
                    }
                  />
                  <Select
                    label="艺术家"
                    options={artistOptions}
                    value={artistId}
                    onChange={(e) => setArtistId(e.target.value)}
                  />
                  {!artistId && (
                    <Select
                      label="自动创建类型"
                      options={artistTypeOptions}
                      value={artistType}
                      onChange={(e) => setArtistType(e.target.value)}
                    />
                  )}
                </div>

                <div className="flex justify-end">
                  <Button
                    type="submit"
                    disabled={
                      !url.trim() ||
                      categoryId === "" ||
                      downloadMutation.isPending ||
                      !!isActiveRunning
                    }
                    className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-md"
                  >
                    {downloadMutation.isPending ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4 mr-2" />
                    )}
                    开始下载
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {/* ========== 共享：下载进度 ========== */}
        {activeTask && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <CardTitle className="text-base">下载进度</CardTitle>
                  <Badge
                    variant={
                      statusConfig[activeTask.status]?.variant ?? "secondary"
                    }
                  >
                    {statusConfig[activeTask.status]?.label ?? activeTask.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  {activeTask.total_count > 0 && (
                    <span className="text-sm text-gray-500">
                      {activeTask.completed_count}/{activeTask.total_count}
                    </span>
                  )}
                  {isActiveRunning && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => cancelMutation.mutate(activeTask.task_id)}
                      disabled={cancelMutation.isPending}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {activeTask.total_count > 0 && (
                <div className="mb-4">
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                </div>
              )}

              {activeTask.error && (
                <div className="mb-3 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-700">
                  {activeTask.error}
                </div>
              )}

              {activeTask.tracks.length > 0 && (
                <div className="space-y-1.5 max-h-80 overflow-y-auto">
                  {activeTask.tracks.map((track) => {
                    const cfg =
                      trackStatusConfig[track.status] ??
                      trackStatusConfig.pending;
                    const Icon = cfg.icon;
                    const isSpinning = [
                      "downloading",
                      "uploading",
                      "creating_record",
                    ].includes(track.status);
                    return (
                      <div
                        key={track.index}
                        className="flex items-center gap-3 py-1.5 px-2 rounded-lg hover:bg-gray-50"
                      >
                        <span className="text-xs text-gray-400 w-5 text-right">
                          {track.index + 1}
                        </span>
                        <Icon
                          className={`h-4 w-4 ${cfg.color} ${
                            isSpinning ? "animate-spin" : ""
                          }`}
                        />
                        <span className="text-sm text-gray-700 truncate flex-1">
                          {track.title}
                        </span>
                        {track.error && (
                          <span className="text-xs text-red-500 truncate max-w-48">
                            {track.error}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ========== 共享：历史任务 ========== */}
        {historyTasks.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">历史任务</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {historyTasks.map((task) => (
                  <div
                    key={task.task_id}
                    className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-50 cursor-pointer"
                    onClick={() => setActiveTaskId(task.task_id)}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {task.status === "completed" ? (
                        <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                      ) : task.status === "failed" ? (
                        <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                      ) : task.status === "cancelled" ? (
                        <X className="h-4 w-4 text-gray-400 shrink-0" />
                      ) : (
                        <Loader2 className="h-4 w-4 text-orange-500 animate-spin shrink-0" />
                      )}
                      <span className="text-sm text-gray-700 truncate">
                        {task.url}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-gray-400">
                        {task.completed_count}/{task.total_count}
                      </span>
                      <Badge
                        variant={
                          statusConfig[task.status]?.variant ?? "secondary"
                        }
                      >
                        {statusConfig[task.status]?.label ?? task.status}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </Layout>
  );
};

export default YouTubeDownload;
