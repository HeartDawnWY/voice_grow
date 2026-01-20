import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  BookOpen,
  Music,
  Languages,
  Settings,
  Volume2,
} from "lucide-react";
import { cn } from "../../lib/utils";

interface NavItem {
  title: string;
  href: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  {
    title: "仪表盘",
    href: "/",
    icon: LayoutDashboard,
  },
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
  {
    title: "系统设置",
    href: "/settings",
    icon: Settings,
  },
];

const Sidebar: React.FC = () => {
  const location = useLocation();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-64 border-r border-gray-200 bg-white">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2 border-b border-gray-200 px-6">
        <Volume2 className="h-8 w-8 text-primary-600" />
        <span className="text-xl font-bold text-gray-900">VoiceGrow</span>
      </div>

      {/* Navigation */}
      <nav className="space-y-1 p-4">
        {navItems.map((item) => {
          const isActive =
            item.href === "/"
              ? location.pathname === "/"
              : location.pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary-50 text-primary-700"
                  : "text-gray-700 hover:bg-gray-100"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.title}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="absolute bottom-0 left-0 right-0 border-t border-gray-200 p-4">
        <div className="text-xs text-gray-500">
          VoiceGrow Admin v0.1.0
        </div>
      </div>
    </aside>
  );
};

export { Sidebar };
