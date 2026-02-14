import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Dashboard from "./pages/Dashboard";
import ContentList from "./pages/contents/ContentList";
import WordList from "./pages/english/WordList";
import CategoryList from "./pages/categories/CategoryList";
import ArtistList from "./pages/artists/ArtistList";
import TagList from "./pages/tags/TagList";
import Settings from "./pages/settings/Settings";
import YouTubeDownload from "./pages/youtube/YouTubeDownload";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route
            path="/contents/stories"
            element={<ContentList key="story" type="story" title="故事管理" />}
          />
          <Route
            path="/contents/music"
            element={<ContentList key="music" type="music" title="音乐管理" />}
          />
          <Route
            path="/contents"
            element={<ContentList key="all" title="内容管理" />}
          />
          <Route path="/english" element={<WordList />} />
          <Route path="/categories" element={<CategoryList />} />
          <Route path="/artists" element={<ArtistList />} />
          <Route path="/tags" element={<TagList />} />
          <Route path="/youtube" element={<YouTubeDownload />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
