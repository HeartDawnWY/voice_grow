import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  BookOpen,
  Music,
  Languages,
  FolderTree,
  Users,
  Tag,
  Settings,
  Mic2,
  Sparkles,
  Download,
} from "lucide-react";

interface NavItem {
  title: string;
  href: string;
  icon: React.ElementType;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    items: [
      {
        title: "仪表盘",
        href: "/",
        icon: LayoutDashboard,
      },
    ],
  },
  {
    label: "内容管理",
    items: [
      {
        title: "故事管理",
        href: "/contents/stories",
        icon: BookOpen,
      },
      {
        title: "音乐管理",
        href: "/contents/music",
        icon: Music,
      },
      {
        title: "英语单词",
        href: "/english",
        icon: Languages,
      },
    ],
  },
  {
    label: "分类体系",
    items: [
      {
        title: "分类管理",
        href: "/categories",
        icon: FolderTree,
      },
      {
        title: "艺术家管理",
        href: "/artists",
        icon: Users,
      },
      {
        title: "标签管理",
        href: "/tags",
        icon: Tag,
      },
    ],
  },
  {
    label: "工具",
    items: [
      {
        title: "YouTube 下载",
        href: "/youtube",
        icon: Download,
      },
    ],
  },
  {
    label: "系统",
    items: [
      {
        title: "系统设置",
        href: "/settings",
        icon: Settings,
      },
    ],
  },
];

// Sound wave component
const SoundWave: React.FC = () => (
  <div className="soundwave">
    <span></span>
    <span></span>
    <span></span>
    <span></span>
    <span></span>
  </div>
);

const Sidebar: React.FC = () => {
  const location = useLocation();

  return (
    <aside className="sidebar fixed left-0 top-0 z-40 h-screen w-64 flex flex-col">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="relative">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center shadow-lg shadow-orange-200">
            <Mic2 className="h-5 w-5 text-white" />
          </div>
          <div className="absolute -top-1 -right-1">
            <Sparkles className="w-4 h-4 text-amber-500" />
          </div>
        </div>
        <div>
          <h1 className="text-lg font-bold text-gray-800 tracking-tight">
            VoiceGrow
          </h1>
          <p className="text-xs text-gray-500 font-medium">声伴成长</p>
        </div>
      </div>

      {/* Divider with soundwave */}
      <div className="px-5 py-3 flex items-center gap-3">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-orange-200 to-transparent" />
        <SoundWave />
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-orange-200 to-transparent" />
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto custom-scrollbar px-3 py-2 space-y-6">
        {navGroups.map((group, groupIndex) => (
          <div key={groupIndex}>
            {group.label && (
              <h2 className="px-3 mb-2 text-xs font-semibold text-gray-400 uppercase tracking-wider">
                {group.label}
              </h2>
            )}
            <div className="space-y-1">
              {group.items.map((item) => {
                const isActive =
                  item.href === "/"
                    ? location.pathname === "/"
                    : location.pathname.startsWith(item.href);

                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    className={`nav-link ${isActive ? "active" : ""}`}
                  >
                    <item.icon className="h-5 w-5" />
                    <span>{item.title}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-orange-200">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500">VoiceGrow Admin</p>
            <p className="text-xs text-gray-400">v0.2.0</p>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-xs text-green-600 font-medium">在线</span>
          </div>
        </div>
      </div>
    </aside>
  );
};

export { Sidebar };
