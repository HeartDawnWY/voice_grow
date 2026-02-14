import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Search, Volume2, Languages, Filter, X } from "lucide-react";
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
import { wordsApi } from "../../api";
import { categoriesApi } from "../../api/categories";
import type { Word } from "../../api";

const levelOptions = [
  { value: "", label: "全部级别" },
  { value: "basic", label: "基础" },
  { value: "elementary", label: "初级" },
  { value: "intermediate", label: "中级" },
];

const WordList: React.FC = () => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [level, setLevel] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingWord, setEditingWord] = useState<Word | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const activeFilterCount = [level, categoryId].filter(v => v !== "").length;

  const [formData, setFormData] = useState({
    word: "",
    phonetic_us: "",
    phonetic_uk: "",
    translation: "",
    level: "basic",
    category_id: 0,
    example_sentence: "",
    example_translation: "",
  });

  // Dynamic category loading
  const { data: categoriesData } = useQuery({
    queryKey: ["categories", "english"],
    queryFn: () => categoriesApi.list("english"),
  });

  // Flatten categories for filter select
  const categoryFilterOptions = React.useMemo(() => {
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
    if (categoriesData) {
      flatten(categoriesData);
    }
    return options;
  }, [categoriesData]);

  // Form category options (without "全部")
  const categoryFormOptions = React.useMemo(() => {
    const options: { value: string; label: string }[] = [
      { value: "0", label: "选择分类" },
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
    if (categoriesData) {
      flatten(categoriesData);
    }
    return options;
  }, [categoriesData]);

  const { data, isLoading } = useQuery({
    queryKey: ["words", { page, level, categoryId, keyword }],
    queryFn: () =>
      wordsApi.list({
        page,
        page_size: 20,
        level: level || undefined,
        category_id: categoryId ? parseInt(categoryId) : undefined,
        keyword: keyword || undefined,
      }),
  });

  const createMutation = useMutation({
    mutationFn: wordsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["words"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`创建失败: ${error.message}`);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: typeof formData }) =>
      wordsApi.update(id, {
        phonetic_us: data.phonetic_us,
        phonetic_uk: data.phonetic_uk,
        translation: data.translation,
        level: data.level,
        category_id: data.category_id || undefined,
        example_sentence: data.example_sentence,
        example_translation: data.example_translation,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["words"] });
      handleFormClose();
    },
    onError: (error: Error) => {
      alert(`更新失败: ${error.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: wordsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["words"] });
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
    setLevel("");
    setCategoryId("");
    setPage(1);
  };

  const handleCreate = () => {
    setEditingWord(null);
    setFormData({
      word: "",
      phonetic_us: "",
      phonetic_uk: "",
      translation: "",
      level: "basic",
      category_id: 0,
      example_sentence: "",
      example_translation: "",
    });
    setIsFormOpen(true);
  };

  const handleEdit = (word: Word) => {
    setEditingWord(word);
    setFormData({
      word: word.word,
      phonetic_us: word.phonetic_us || "",
      phonetic_uk: word.phonetic_uk || "",
      translation: word.translation,
      level: word.level,
      category_id: word.category_id || 0,
      example_sentence: word.example_sentence || "",
      example_translation: word.example_translation || "",
    });
    setIsFormOpen(true);
  };

  const handleFormClose = () => {
    setIsFormOpen(false);
    setEditingWord(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingWord) {
      updateMutation.mutate({ id: editingWord.id, data: formData });
    } else {
      createMutation.mutate({
        word: formData.word,
        phonetic_us: formData.phonetic_us,
        phonetic_uk: formData.phonetic_uk,
        translation: formData.translation,
        level: formData.level,
        category_id: formData.category_id || undefined,
        example_sentence: formData.example_sentence,
        example_translation: formData.example_translation,
      });
    }
  };

  const handleDelete = (word: Word) => {
    if (window.confirm(`确定要删除单词 "${word.word}" 吗？`)) {
      deleteMutation.mutate(word.id);
    }
  };

  const playAudio = (url?: string) => {
    if (url) {
      const audio = new Audio(url);
      audio.play();
    }
  };

  const getLevelBadge = (lvl: string) => {
    switch (lvl) {
      case "basic":
        return <Badge variant="success">基础</Badge>;
      case "elementary":
        return <Badge variant="default">初级</Badge>;
      case "intermediate":
        return <Badge variant="warning">中级</Badge>;
      default:
        return <Badge variant="secondary">{lvl}</Badge>;
    }
  };

  return (
    <Layout title="英语单词">
      <div className="space-y-5">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-600 flex items-center justify-center shadow-lg">
              <Languages className="w-6 h-6 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-800">英语单词</h2>
              <p className="text-gray-500 text-sm">共 {data?.total ?? 0} 个单词</p>
            </div>
          </div>
          <Button onClick={handleCreate} className="bg-gradient-to-r from-emerald-500 to-emerald-600 text-white shadow-lg">
            <Plus className="h-4 w-4 mr-2" />
            添加单词
          </Button>
        </div>

        {/* Toolbar */}
        <div className="card flex items-center gap-4 p-4">
          <div className="flex items-center gap-2 flex-1">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="搜索单词..."
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
            <div className="w-[160px]">
              <Select
                variant="filter"
                label="级别"
                value={level}
                onChange={(e) => {
                  setLevel(e.target.value);
                  setPage(1);
                }}
                options={levelOptions}
              />
            </div>
            <div className="w-[180px]">
              <Select
                variant="filter"
                label="分类"
                value={categoryId}
                onChange={(e) => {
                  setCategoryId(e.target.value);
                  setPage(1);
                }}
                options={categoryFilterOptions}
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
                <TableHead>单词</TableHead>
                <TableHead>音标</TableHead>
                <TableHead>翻译</TableHead>
                <TableHead className="w-20">级别</TableHead>
                <TableHead className="w-20">分类</TableHead>
                <TableHead className="w-32 text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-8 h-8 border-3 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                      <span className="text-gray-400">加载中...</span>
                    </div>
                  </TableCell>
                </TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-14 h-14 rounded-xl bg-emerald-50 flex items-center justify-center">
                        <Languages className="w-6 h-6 text-emerald-500" />
                      </div>
                      <div>
                        <p className="text-gray-600 font-medium">暂无单词</p>
                        <p className="text-gray-400 text-sm">点击上方按钮添加第一个单词</p>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                data?.items.map((word) => (
                  <TableRow key={word.id} className="table-row">
                    <TableCell>
                      <span className="font-mono text-gray-400 text-xs bg-stone-100 px-2 py-1 rounded">
                        #{word.id}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-500 flex items-center justify-center text-white font-bold text-sm">
                          {word.word[0]?.toUpperCase()}
                        </div>
                        <span className="font-medium text-gray-800">{word.word}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-500 font-mono text-sm">
                        {word.phonetic_us || "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-gray-600">{word.translation}</span>
                    </TableCell>
                    <TableCell>{getLevelBadge(word.level)}</TableCell>
                    <TableCell>
                      <span className="text-gray-500">{word.category_name || "-"}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {word.audio_us_url && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => playAudio(word.audio_us_url)}
                            className="hover:bg-blue-50 hover:text-blue-500"
                          >
                            <Volume2 className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleEdit(word)}
                          className="hover:bg-orange-50 hover:text-orange-600"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(word)}
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
            {editingWord ? "编辑单词" : "添加单词"}
          </DialogHeader>
          <DialogContent className="space-y-4">
            <Input
              label="单词"
              value={formData.word}
              onChange={(e) =>
                setFormData({ ...formData, word: e.target.value })
              }
              required
              disabled={!!editingWord}
            />
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="美式音标"
                value={formData.phonetic_us}
                onChange={(e) =>
                  setFormData({ ...formData, phonetic_us: e.target.value })
                }
                placeholder="/ˈæpəl/"
              />
              <Input
                label="英式音标"
                value={formData.phonetic_uk}
                onChange={(e) =>
                  setFormData({ ...formData, phonetic_uk: e.target.value })
                }
                placeholder="/ˈæpəl/"
              />
            </div>
            <Input
              label="翻译"
              value={formData.translation}
              onChange={(e) =>
                setFormData({ ...formData, translation: e.target.value })
              }
              required
            />
            <div className="grid grid-cols-2 gap-4">
              <Select
                label="级别"
                options={levelOptions.filter((o) => o.value)}
                value={formData.level}
                onChange={(e) =>
                  setFormData({ ...formData, level: e.target.value })
                }
              />
              <Select
                label="分类"
                options={categoryFormOptions}
                value={String(formData.category_id)}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    category_id: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
            <Textarea
              label="例句"
              value={formData.example_sentence}
              onChange={(e) =>
                setFormData({ ...formData, example_sentence: e.target.value })
              }
              placeholder="I eat an apple every day."
            />
            <Textarea
              label="例句翻译"
              value={formData.example_translation}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  example_translation: e.target.value,
                })
              }
              placeholder="我每天吃一个苹果。"
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

export default WordList;
