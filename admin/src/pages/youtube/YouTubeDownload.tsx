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
import { youtubeApi, categoriesApi, artistsApi } from "../../api";

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

const YouTubeDownload: React.FC = () => {
  const queryClient = useQueryClient();

  // Form state
  const [url, setUrl] = useState("");
  const [contentType, setContentType] = useState("music");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [artistId, setArtistId] = useState<string>(""); // "" = auto, "id" = existing
  const [artistType, setArtistType] = useState("singer");

  // Active task tracking
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  // Categories for selected content type
  const categoryType = contentType === "story" ? "story" : "music";
  const { data: categories = [] } = useQuery({
    queryKey: ["categories", categoryType],
    queryFn: () => categoriesApi.list(categoryType),
  });

  // Artists list
  const { data: artistsData } = useQuery({
    queryKey: ["artists", { page_size: 100 }],
    queryFn: () => artistsApi.list({ page_size: 100 }),
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
        result.push({
          value: String(a.id),
          label: `${a.name} (${typeLabel})`,
        });
      }
    }
    return result;
  }, [artistsData]);

  // Flatten categories (include children)
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

  // Poll active task
  const { data: activeTask } = useQuery({
    queryKey: ["youtube-task", activeTaskId],
    queryFn: () => youtubeApi.getTask(activeTaskId!),
    enabled: !!activeTaskId,
    refetchInterval: (query) => {
      const task = query.state.data;
      if (!task || TERMINAL_STATUSES.includes(task.status)) return false;
      return 2500;
    },
  });

  // Task list
  const { data: taskList = [] } = useQuery({
    queryKey: ["youtube-tasks"],
    queryFn: () => youtubeApi.listTasks(),
    refetchInterval: 10000,
  });

  // Start download mutation
  const downloadMutation = useMutation({
    mutationFn: youtubeApi.startDownload,
    onSuccess: (task) => {
      setActiveTaskId(task.task_id);
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["youtube-tasks"] });
    },
    onError: (error: Error) => {
      alert(`下载失败: ${error.message}`);
    },
  });

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: youtubeApi.cancelTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["youtube-task", activeTaskId] });
      queryClient.invalidateQueries({ queryKey: ["youtube-tasks"] });
    },
  });

  // Invalidate task list when active task finishes
  useEffect(() => {
    if (activeTask && TERMINAL_STATUSES.includes(activeTask.status)) {
      queryClient.invalidateQueries({ queryKey: ["youtube-tasks"] });
    }
  }, [activeTask?.status, queryClient]);

  // Resolve selected artist name
  const selectedArtist = React.useMemo(() => {
    if (!artistId || !artistsData?.items) return null;
    return artistsData.items.find((a) => String(a.id) === artistId) ?? null;
  }, [artistId, artistsData]);

  const handleSubmit = (e: React.FormEvent) => {
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

  // History: exclude the active task
  const historyTasks = taskList.filter(
    (t) => t.task_id !== activeTaskId
  );

  return (
    <Layout title="YouTube 下载">
      <div className="space-y-6">
        {/* Page header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500 to-rose-600 flex items-center justify-center shadow-lg shadow-red-200">
            <Download className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-800">YouTube 下载</h2>
            <p className="text-sm text-gray-500">
              从 YouTube 下载音频，自动转码并创建内容记录
            </p>
          </div>
        </div>

        {/* Download form */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">新建下载</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* URL input */}
              <div className="relative">
                <Link className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <Input
                  className="pl-10"
                  placeholder="YouTube 视频或播放列表 URL"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>

              {/* Options grid */}
              <div className={`grid grid-cols-2 ${!artistId ? "md:grid-cols-4" : "md:grid-cols-3"} gap-3`}>
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

              {/* Submit */}
              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={
                    !url.trim() ||
                    categoryId === "" ||
                    downloadMutation.isPending ||
                    !!isActiveRunning
                  }
                  className="bg-gradient-to-r from-red-500 to-rose-600 hover:from-red-600 hover:to-rose-700 text-white shadow-md"
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

        {/* Active task progress */}
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
              {/* Progress bar */}
              {activeTask.total_count > 0 && (
                <div className="mb-4">
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-red-500 to-rose-500 rounded-full transition-all duration-500"
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Error message */}
              {activeTask.error && (
                <div className="mb-3 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-700">
                  {activeTask.error}
                </div>
              )}

              {/* Track list */}
              {activeTask.tracks.length > 0 && (
                <div className="space-y-1.5 max-h-80 overflow-y-auto">
                  {activeTask.tracks.map((track) => {
                    const cfg = trackStatusConfig[track.status] ?? trackStatusConfig.pending;
                    const Icon = cfg.icon;
                    const isSpinning = ["downloading", "uploading", "creating_record"].includes(
                      track.status
                    );
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

        {/* Task history */}
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
