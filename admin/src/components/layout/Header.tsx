import React from "react";
import { Bell, Search, User, ChevronRight, Home } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

interface HeaderProps {
  title?: string;
}

// Breadcrumb mapping
const breadcrumbNames: Record<string, string> = {
  "": "首页",
  "contents": "内容管理",
  "stories": "故事",
  "music": "音乐",
  "english": "英语单词",
  "categories": "分类管理",
  "artists": "艺术家管理",
  "tags": "标签管理",
  "settings": "系统设置",
};

const Header: React.FC<HeaderProps> = ({ title }) => {
  const location = useLocation();
  const pathSegments = location.pathname.split("/").filter(Boolean);

  return (
    <header className="sticky top-0 z-30 bg-white/80 backdrop-blur-md border-b border-stone-200">
      <div className="flex h-16 items-center justify-between px-6">
        {/* Left: Breadcrumb & Title */}
        <div className="flex flex-col">
          {/* Breadcrumb */}
          <nav className="flex items-center text-sm text-gray-500">
            <Link to="/" className="hover:text-orange-500 transition-colors flex items-center gap-1">
              <Home className="w-3.5 h-3.5" />
              <span>首页</span>
            </Link>
            {pathSegments.map((segment, index) => (
              <React.Fragment key={segment}>
                <ChevronRight className="w-3.5 h-3.5 mx-1.5 text-gray-300" />
                <span className={index === pathSegments.length - 1 ? "text-gray-700 font-medium" : ""}>
                  {breadcrumbNames[segment] || segment}
                </span>
              </React.Fragment>
            ))}
          </nav>
          {/* Title */}
          {title && (
            <h1 className="text-xl font-bold text-gray-800 mt-0.5">
              {title}
            </h1>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative hidden md:block group">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-orange-500 transition-colors" />
            <input
              type="search"
              placeholder="搜索内容..."
              className="w-56 h-9 pl-10 pr-4 rounded-lg border border-stone-200 bg-white text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500/20 focus:border-orange-400 transition-all"
            />
          </div>

          {/* Notifications */}
          <button className="relative w-9 h-9 rounded-lg bg-white border border-stone-200 flex items-center justify-center hover:bg-stone-50 hover:border-stone-300 transition-all">
            <Bell className="h-4 w-4 text-gray-500" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-orange-500 ring-2 ring-white" />
          </button>

          {/* User */}
          <button className="flex items-center gap-2 h-9 pl-1 pr-3 rounded-lg bg-white border border-stone-200 hover:bg-stone-50 hover:border-stone-300 transition-all">
            <div className="w-7 h-7 rounded-md bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center">
              <User className="h-4 w-4 text-white" />
            </div>
            <span className="text-sm font-medium text-gray-700">管理员</span>
          </button>
        </div>
      </div>
    </header>
  );
};

export { Header };
