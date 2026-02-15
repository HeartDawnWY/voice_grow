import React, { useState, useRef, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Upload, X, Music, CheckCircle, AlertCircle, Loader2,
  SkipForward, Folder,
} from "lucide-react";
import {
  Dialog,
  DialogHeader,
  DialogContent,
  DialogFooter,
  Button,
  Select,
} from "../../components/ui";
import { contentsApi, uploadApi } from "../../api";
import { categoriesApi } from "../../api/categories";
import { tagsApi } from "../../api/tags";
import { artistsApi } from "../../api/artists";
import type { ContentType } from "../../api";
import type { Artist } from "../../api/artists";

interface BatchUploadFormProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  defaultType?: ContentType;
}

interface ParsedFile {
  file: File;
  title: string;
  artistNames: string[];
  artistSource: "filename" | "folder" | "none";
  matchedArtistIds: Array<{ id: number; role: string; is_primary: boolean }>;
  status: "pending" | "uploading" | "success" | "error" | "exists";
  error?: string;
  progress: number;
}

const AUDIO_EXTENSIONS = /\.(mp3|wav|flac|m4a|ogg|aac|wma|opus|ape)$/i;

/** Parse filename like "Artist1&Artist2-Song Title.wav" */
function parseFilename(filename: string): { title: string; artistNames: string[] } {
  const nameWithoutExt = filename.replace(/\.[^.]+$/, "");

  let artistPart = "";
  let titlePart = nameWithoutExt;

  const dashWithSpaces = nameWithoutExt.indexOf(" - ");
  if (dashWithSpaces !== -1) {
    artistPart = nameWithoutExt.substring(0, dashWithSpaces);
    titlePart = nameWithoutExt.substring(dashWithSpaces + 3);
  } else {
    const dashIndex = nameWithoutExt.indexOf("-");
    if (dashIndex !== -1) {
      artistPart = nameWithoutExt.substring(0, dashIndex);
      titlePart = nameWithoutExt.substring(dashIndex + 1);
    }
  }

  const artistNames = artistPart
    ? artistPart.split("&").map((s) => s.trim()).filter(Boolean)
    : [];

  return { title: titlePart.trim(), artistNames };
}

/** Get parent folder name from webkitRelativePath */
function getParentFolder(file: File): string {
  const relativePath = file.webkitRelativePath;
  if (!relativePath) return "";
  const parts = relativePath.split("/");
  // ["TopFolder", "SubFolder", "file.mp3"] → parent = "SubFolder"
  // ["TopFolder", "file.mp3"] → parent = "TopFolder" (selected folder itself)
  if (parts.length >= 3) {
    return parts[parts.length - 2];
  }
  if (parts.length === 2) {
    return parts[0];
  }
  return "";
}

/** Match parsed artist names against the existing artist list */
function matchArtists(
  artistNames: string[],
  allArtists: Artist[]
): Array<{ id: number; role: string; is_primary: boolean }> {
  return artistNames
    .map((name, idx) => {
      const match = allArtists.find(
        (a) => a.name.toLowerCase() === name.toLowerCase()
      );
      return match
        ? { id: match.id, role: "singer", is_primary: idx === 0 }
        : null;
    })
    .filter((m): m is NonNullable<typeof m> => m !== null);
}

const BatchUploadForm: React.FC<BatchUploadFormProps> = ({
  open,
  onClose,
  onSuccess,
  defaultType,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<ParsedFile[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Shared fields
  const [sharedCategoryId, setSharedCategoryId] = useState(0);
  const [sharedTagIds, setSharedTagIds] = useState<number[]>([]);
  const [sharedArtistIds, setSharedArtistIds] = useState<number[]>([]);
  const [sharedAgeMin, setSharedAgeMin] = useState(0);
  const [sharedAgeMax, setSharedAgeMax] = useState(12);

  const contentType = defaultType || "music";

  // Reset all state when dialog opens (handles onSuccess path that bypasses handleClose)
  useEffect(() => {
    if (open) {
      setFiles([]);
      setIsSubmitting(false);
      setSharedCategoryId(0);
      setSharedTagIds([]);
      setSharedArtistIds([]);
      setSharedAgeMin(0);
      setSharedAgeMax(12);
    }
  }, [open]);

  const { data: categoriesData } = useQuery({
    queryKey: ["categories", contentType],
    queryFn: () => categoriesApi.list(contentType),
    enabled: open,
  });

  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => tagsApi.list(),
    enabled: open,
  });

  const { data: artistsData } = useQuery({
    queryKey: ["artists-all"],
    queryFn: async () => {
      const res = await artistsApi.list({ page_size: 100 });
      return res.items;
    },
    enabled: open,
  });

  const { data: existingTitles } = useQuery({
    queryKey: ["existing-titles", contentType],
    queryFn: async () => {
      const titles = new Set<string>();
      let page = 1;
      while (true) {
        const res = await contentsApi.list({ type: contentType, page, page_size: 200 });
        res.items.forEach((item) => titles.add(item.title));
        if (page >= res.total_pages) break;
        page++;
      }
      return titles;
    },
    enabled: open,
  });

  const categoryOptions = useMemo(() => {
    const options: { value: string; label: string }[] = [
      { value: "0", label: "选择分类" },
    ];
    const flatten = (
      cats: Array<{ id: number; name: string; children?: any[] }>,
      prefix = ""
    ) => {
      for (const cat of cats) {
        options.push({ value: String(cat.id), label: prefix + cat.name });
        if (cat.children?.length) flatten(cat.children, prefix + "  ");
      }
    };
    if (categoriesData) flatten(categoriesData);
    return options;
  }, [categoriesData]);

  /** Core processing: parse files → match artists → check duplicates */
  const processFiles = (fileList: FileList) => {
    const allArtists = artistsData || [];
    const titleSet = existingTitles || new Set<string>();

    const audioFiles = Array.from(fileList).filter(
      (f) => f.type.startsWith("audio/") || AUDIO_EXTENSIONS.test(f.name)
    );

    const newFiles: ParsedFile[] = audioFiles.map((file) => {
      const { title, artistNames } = parseFilename(file.name);

      // Fallback: if no artist from filename, try parent folder name
      let finalArtistNames = artistNames;
      let artistSource: ParsedFile["artistSource"] = artistNames.length > 0 ? "filename" : "none";

      if (finalArtistNames.length === 0) {
        const folderName = getParentFolder(file);
        if (folderName) {
          finalArtistNames = [folderName];
          artistSource = "folder";
        }
      }

      const matchedArtistIds = matchArtists(finalArtistNames, allArtists);
      const isDuplicate = titleSet.has(title);

      return {
        file,
        title,
        artistNames: finalArtistNames,
        artistSource,
        matchedArtistIds,
        status: isDuplicate ? ("exists" as const) : ("pending" as const),
        progress: 0,
      };
    });

    setFiles((prev) => [...prev, ...newFiles]);
  };

  const handleFilesSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files;
    if (!selectedFiles?.length) return;
    processFiles(selectedFiles);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleFolderSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files;
    if (!selectedFiles?.length) return;
    processFiles(selectedFiles);
    if (folderInputRef.current) folderInputRef.current.value = "";
  };

  const handleRemoveFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleTitleChange = (index: number, title: string) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === index ? { ...f, title } : f))
    );
  };

  const handleArtistChange = (index: number, artistId: number, checked: boolean) => {
    setFiles((prev) =>
      prev.map((f, i) => {
        if (i !== index) return f;
        let next = [...f.matchedArtistIds];
        if (checked) {
          next.push({ id: artistId, role: "singer", is_primary: next.length === 0 });
        } else {
          next = next.filter((a) => a.id !== artistId);
          if (next.length > 0 && !next.some((a) => a.is_primary)) {
            next[0] = { ...next[0], is_primary: true };
          }
        }
        return { ...f, matchedArtistIds: next };
      })
    );
  };

  const handleSharedArtistToggle = (artistId: number) => {
    setSharedArtistIds((prev) =>
      prev.includes(artistId)
        ? prev.filter((id) => id !== artistId)
        : [...prev, artistId]
    );
  };

  const handleTagToggle = (tagId: number) => {
    setSharedTagIds((prev) =>
      prev.includes(tagId)
        ? prev.filter((id) => id !== tagId)
        : [...prev, tagId]
    );
  };

  const handleSubmit = async () => {
    if (files.length === 0) return;

    setIsSubmitting(true);
    const folder = contentType === "story" ? "stories" : contentType === "music" ? "music" : "english";

    // Build shared artist entries
    const sharedArtistEntries = sharedArtistIds.map((id) => ({
      id,
      role: "singer",
    }));

    let hasAnySuccess = false;

    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      if (f.status === "success" || f.status === "exists") continue;

      setFiles((prev) =>
        prev.map((item, idx) =>
          idx === i ? { ...item, status: "uploading", progress: 0, error: undefined } : item
        )
      );

      try {
        const objectName = await uploadApi.uploadFile(
          f.file,
          folder as any,
          (percent) => {
            setFiles((prev) =>
              prev.map((item, idx) =>
                idx === i ? { ...item, progress: percent } : item
              )
            );
          }
        );

        // Merge artists: per-file first, then shared (deduplicated)
        const finalArtists = [...f.matchedArtistIds];
        for (const sa of sharedArtistEntries) {
          if (!finalArtists.some((a) => a.id === sa.id)) {
            finalArtists.push({
              ...sa,
              is_primary: finalArtists.length === 0,
            });
          }
        }

        await contentsApi.create({
          type: contentType,
          title: f.title,
          category_id: sharedCategoryId,
          minio_path: objectName,
          tag_ids: sharedTagIds.length > 0 ? sharedTagIds : undefined,
          artist_ids: finalArtists.length > 0 ? finalArtists : undefined,
          age_min: sharedAgeMin,
          age_max: sharedAgeMax,
        });

        setFiles((prev) =>
          prev.map((item, idx) =>
            idx === i ? { ...item, status: "success", progress: 100 } : item
          )
        );
        hasAnySuccess = true;
      } catch (err: any) {
        setFiles((prev) =>
          prev.map((item, idx) =>
            idx === i
              ? { ...item, status: "error", error: err?.message || "上传失败" }
              : item
          )
        );
      }
    }

    setIsSubmitting(false);
    if (hasAnySuccess) onSuccess();
  };

  const handleClose = () => {
    if (isSubmitting) return;
    setFiles([]);
    setSharedCategoryId(0);
    setSharedTagIds([]);
    setSharedArtistIds([]);
    setSharedAgeMin(0);
    setSharedAgeMax(12);
    onClose();
  };

  const pendingCount = files.filter((f) => f.status === "pending").length;
  const successCount = files.filter((f) => f.status === "success").length;
  const errorCount = files.filter((f) => f.status === "error").length;
  const existsCount = files.filter((f) => f.status === "exists").length;
  const allDone = files.length > 0 && pendingCount === 0 && !isSubmitting;

  const unmatchedNames = useMemo(() => {
    const names = new Set<string>();
    files.forEach((f) => {
      f.artistNames.forEach((name) => {
        const matched = artistsData?.find(
          (a) => a.name.toLowerCase() === name.toLowerCase()
        );
        if (!matched) names.add(name);
      });
    });
    return Array.from(names);
  }, [files, artistsData]);

  const artistSourceLabel = (source: ParsedFile["artistSource"]) => {
    switch (source) {
      case "filename": return "文件名:";
      case "folder": return "文件夹:";
      default: return null;
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} className="max-w-4xl">
      <DialogHeader onClose={handleClose}>批量添加内容</DialogHeader>

      <DialogContent className="space-y-4 max-h-[70vh] overflow-y-auto">
        {/* File Selection Area */}
        <div className="flex gap-3">
          {/* Select files */}
          <div
            className="flex-1 border-2 border-dashed border-gray-300 rounded-xl p-5 text-center hover:border-violet-400 hover:bg-violet-50/30 transition-colors cursor-pointer"
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              multiple
              className="hidden"
              onChange={handleFilesSelected}
              disabled={isSubmitting}
            />
            <Upload className="w-8 h-8 text-gray-400 mx-auto mb-1.5" />
            <p className="text-sm text-gray-600 font-medium">选择文件</p>
            <p className="text-xs text-gray-400 mt-1">支持多选</p>
          </div>

          {/* Select folder */}
          <div
            className="flex-1 border-2 border-dashed border-gray-300 rounded-xl p-5 text-center hover:border-violet-400 hover:bg-violet-50/30 transition-colors cursor-pointer"
            onClick={() => folderInputRef.current?.click()}
          >
            <input
              ref={folderInputRef}
              type="file"
              className="hidden"
              onChange={handleFolderSelected}
              disabled={isSubmitting}
              {...{ webkitdirectory: "", directory: "" } as any}
            />
            <Folder className="w-8 h-8 text-gray-400 mx-auto mb-1.5" />
            <p className="text-sm text-gray-600 font-medium">选择文件夹</p>
            <p className="text-xs text-gray-400 mt-1">自动识别文件夹名为歌手</p>
          </div>
        </div>
        <p className="text-xs text-gray-400 text-center -mt-2">
          文件名格式: 歌手-歌曲名.mp3 / 歌手A&歌手B-歌曲名.wav / 歌曲名.wav
        </p>

        {/* Unmatched artist warning */}
        {unmatchedNames.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
            <span className="font-medium">未匹配到的歌手: </span>
            {unmatchedNames.join("、")}
            <span className="text-amber-500 ml-1">
              （请先在艺术家管理中添加，或手动关联已有歌手）
            </span>
          </div>
        )}

        {/* File List */}
        {files.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm text-gray-500">
              <span>
                共 {files.length} 个文件
                {existsCount > 0 && (
                  <span className="text-amber-500 ml-2">已存在 {existsCount}</span>
                )}
                {successCount > 0 && (
                  <span className="text-green-600 ml-2">成功 {successCount}</span>
                )}
                {errorCount > 0 && (
                  <span className="text-red-500 ml-2">失败 {errorCount}</span>
                )}
              </span>
              {!isSubmitting && (pendingCount > 0 || existsCount > 0) && (
                <button
                  className="text-xs text-red-400 hover:text-red-600"
                  onClick={() =>
                    setFiles((prev) => prev.filter((f) => f.status === "success"))
                  }
                >
                  清除未上传
                </button>
              )}
            </div>

            <div className="border rounded-lg divide-y max-h-[300px] overflow-y-auto">
              {files.map((f, idx) => (
                <div
                  key={idx}
                  className={`px-3 py-2.5 text-sm ${
                    f.status === "success"
                      ? "bg-green-50/50"
                      : f.status === "error"
                        ? "bg-red-50/50"
                        : f.status === "exists"
                          ? "bg-amber-50/50 opacity-60"
                          : ""
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Status icon */}
                    <div className="mt-0.5">
                      {f.status === "success" ? (
                        <CheckCircle className="w-4 h-4 text-green-500" />
                      ) : f.status === "error" ? (
                        <AlertCircle className="w-4 h-4 text-red-500" />
                      ) : f.status === "uploading" ? (
                        <Loader2 className="w-4 h-4 text-violet-500 animate-spin" />
                      ) : f.status === "exists" ? (
                        <SkipForward className="w-4 h-4 text-amber-500" />
                      ) : (
                        <Music className="w-4 h-4 text-gray-400" />
                      )}
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0 space-y-1.5">
                      {/* Title row */}
                      <div className="flex items-center gap-2">
                        {f.status === "pending" ? (
                          <input
                            className="flex-1 text-sm border border-gray-200 rounded px-2 py-0.5 focus:outline-none focus:border-violet-400"
                            value={f.title}
                            onChange={(e) => handleTitleChange(idx, e.target.value)}
                          />
                        ) : (
                          <span className="flex-1 font-medium text-gray-800 truncate">
                            {f.title}
                          </span>
                        )}
                        {f.status === "exists" && (
                          <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded shrink-0">
                            已存在，跳过
                          </span>
                        )}
                        <span className="text-xs text-gray-400 shrink-0">
                          {(f.file.size / 1024 / 1024).toFixed(1)}MB
                        </span>
                      </div>

                      {/* Artist chips */}
                      <div className="flex flex-wrap gap-1 items-center">
                        {f.artistNames.length > 0 ? (
                          <span className="text-xs text-gray-400 mr-1">
                            {artistSourceLabel(f.artistSource)}
                          </span>
                        ) : f.status !== "exists" ? (
                          <span className="text-xs text-gray-400 mr-1">
                            未识别歌手
                          </span>
                        ) : null}
                        {f.artistNames.map((name, ni) => {
                          const matched = artistsData?.find(
                            (a) => a.name.toLowerCase() === name.toLowerCase()
                          );
                          return (
                            <span
                              key={ni}
                              className={`inline-flex items-center text-xs px-1.5 py-0.5 rounded ${
                                matched
                                  ? "bg-violet-100 text-violet-700"
                                  : "bg-gray-100 text-gray-500 line-through"
                              }`}
                            >
                              {name}
                              {matched && " \u2713"}
                            </span>
                          );
                        })}
                        {/* Manual artist selector for pending items */}
                        {f.status === "pending" && artistsData && (
                          <div className="relative group">
                            <button
                              type="button"
                              className="text-xs text-violet-500 hover:text-violet-700 px-1"
                            >
                              + 关联歌手
                            </button>
                            <div className="absolute left-0 top-full mt-1 bg-white border rounded-lg shadow-lg p-2 hidden group-hover:block z-10 w-48 max-h-40 overflow-y-auto">
                              {artistsData.map((a) => (
                                <label
                                  key={a.id}
                                  className="flex items-center gap-1.5 px-2 py-1 hover:bg-gray-50 rounded cursor-pointer text-xs"
                                >
                                  <input
                                    type="checkbox"
                                    className="rounded"
                                    checked={f.matchedArtistIds.some((m) => m.id === a.id)}
                                    onChange={(e) =>
                                      handleArtistChange(idx, a.id, e.target.checked)
                                    }
                                  />
                                  {a.name}
                                </label>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Progress bar */}
                      {f.status === "uploading" && (
                        <div className="w-full bg-gray-100 rounded-full h-1.5">
                          <div
                            className="bg-violet-500 h-1.5 rounded-full transition-all"
                            style={{ width: `${f.progress}%` }}
                          />
                        </div>
                      )}

                      {/* Error message */}
                      {f.status === "error" && f.error && (
                        <p className="text-xs text-red-500">{f.error}</p>
                      )}
                    </div>

                    {/* Remove button */}
                    {(f.status === "pending" || f.status === "exists") && !isSubmitting && (
                      <button
                        className="text-gray-300 hover:text-red-500 mt-0.5"
                        onClick={() => handleRemoveFile(idx)}
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Shared Settings */}
        {files.length > 0 && (
          <div className="border rounded-lg p-4 space-y-3 bg-gray-50/50">
            <h4 className="text-sm font-medium text-gray-600">
              共享设置（应用到所有文件）
            </h4>

            <Select
              label="分类"
              options={categoryOptions}
              value={String(sharedCategoryId)}
              onChange={(e) => setSharedCategoryId(parseInt(e.target.value) || 0)}
            />

            {/* Shared Artists — applied to all files */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                统一关联歌手
                <span className="text-xs text-gray-400 font-normal ml-1">
                  （与每首歌单独关联的歌手合并）
                </span>
              </label>
              <div className="flex flex-wrap gap-2">
                {artistsData?.map((artist) => (
                  <label
                    key={artist.id}
                    className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs cursor-pointer border transition-colors ${
                      sharedArtistIds.includes(artist.id)
                        ? "bg-violet-100 border-violet-400 text-violet-700"
                        : "bg-white border-gray-200 text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={sharedArtistIds.includes(artist.id)}
                      onChange={() => handleSharedArtistToggle(artist.id)}
                    />
                    {artist.name}
                  </label>
                ))}
                {(!artistsData || artistsData.length === 0) && (
                  <span className="text-xs text-gray-400">暂无艺术家</span>
                )}
              </div>
            </div>

            {/* Tags */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                标签
              </label>
              <div className="flex flex-wrap gap-2">
                {tagsData?.map((tag) => (
                  <label
                    key={tag.id}
                    className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs cursor-pointer border transition-colors ${
                      sharedTagIds.includes(tag.id)
                        ? "bg-primary-100 border-primary-500 text-primary-700"
                        : "bg-white border-gray-200 text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={sharedTagIds.includes(tag.id)}
                      onChange={() => handleTagToggle(tag.id)}
                    />
                    {tag.name}
                  </label>
                ))}
                {(!tagsData || tagsData.length === 0) && (
                  <span className="text-xs text-gray-400">暂无标签</span>
                )}
              </div>
            </div>

            {/* Age Range */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  最小年龄
                </label>
                <input
                  type="number"
                  className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                  value={sharedAgeMin}
                  onChange={(e) => setSharedAgeMin(parseInt(e.target.value) || 0)}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  最大年龄
                </label>
                <input
                  type="number"
                  className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                  value={sharedAgeMax}
                  onChange={(e) => setSharedAgeMax(parseInt(e.target.value) || 12)}
                />
              </div>
            </div>
          </div>
        )}
      </DialogContent>

      <DialogFooter>
        {allDone ? (
          <Button onClick={handleClose}>完成</Button>
        ) : (
          <>
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={isSubmitting || files.length === 0 || pendingCount === 0}
              className="bg-gradient-to-r from-violet-500 to-violet-600 text-white"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  上传中...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 mr-1" />
                  开始上传 ({pendingCount} 个)
                </>
              )}
            </Button>
          </>
        )}
      </DialogFooter>
    </Dialog>
  );
};

export default BatchUploadForm;
