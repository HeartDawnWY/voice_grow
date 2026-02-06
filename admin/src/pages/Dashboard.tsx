import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Music,
  Languages,
  FileText,
  TrendingUp,
  Plus,
  ArrowRight,
  Sparkles,
  Clock,
  Zap,
  Volume2,
} from "lucide-react";
import { Layout } from "../components/layout";
import { statsApi } from "../api";

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ElementType;
  color: string;
  bgColor: string;
  trend?: number;
  href?: string;
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon: Icon,
  color,
  bgColor,
  trend,
  href,
}) => {
  const content = (
    <div className="card stat-card p-5 hover:shadow-lg transition-all duration-300 cursor-pointer group">
      <div className="flex items-start justify-between">
        <div className={`w-12 h-12 rounded-xl ${bgColor} flex items-center justify-center`}>
          <Icon className={`h-6 w-6 ${color}`} />
        </div>
        {trend !== undefined && (
          <div className="flex items-center gap-1 text-green-600 text-sm font-medium bg-green-50 px-2 py-0.5 rounded-full">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>+{trend}%</span>
          </div>
        )}
      </div>
      <div className="mt-4">
        <p className="text-gray-500 text-sm font-medium">{title}</p>
        <p className="text-3xl font-bold text-gray-800 mt-1">
          {value.toLocaleString()}
        </p>
      </div>
      {href && (
        <div className="mt-4 pt-3 border-t border-stone-100 flex items-center text-sm text-gray-400 group-hover:text-orange-500 transition-colors">
          <span>查看详情</span>
          <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
        </div>
      )}
    </div>
  );

  return href ? <Link to={href}>{content}</Link> : content;
};

interface QuickActionProps {
  title: string;
  description: string;
  icon: React.ElementType;
  href: string;
  color: string;
}

const QuickAction: React.FC<QuickActionProps> = ({
  title,
  description,
  icon: Icon,
  href,
  color,
}) => (
  <Link
    to={href}
    className="card p-4 flex items-center gap-4 hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 group"
  >
    <div className={`w-11 h-11 rounded-xl ${color} flex items-center justify-center group-hover:scale-110 transition-transform`}>
      <Icon className="w-5 h-5 text-white" />
    </div>
    <div className="flex-1">
      <h3 className="font-semibold text-gray-800 group-hover:text-orange-600 transition-colors">
        {title}
      </h3>
      <p className="text-sm text-gray-500">{description}</p>
    </div>
    <Plus className="w-5 h-5 text-gray-300 group-hover:text-orange-500 transition-colors" />
  </Link>
);

const Dashboard: React.FC = () => {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: statsApi.get,
  });

  return (
    <Layout title="仪表盘">
      <div className="space-y-6">
        {/* Welcome Banner */}
        <div className="card overflow-hidden">
          <div className="relative bg-gradient-to-r from-orange-500 to-amber-500 p-6">
            {/* Decorative circles */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -translate-y-1/2 translate-x-1/2" />
            <div className="absolute bottom-0 left-1/4 w-20 h-20 bg-white/10 rounded-full translate-y-1/2" />

            <div className="relative z-10 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="w-5 h-5 text-yellow-200" />
                  <span className="text-orange-100 text-sm font-medium">欢迎回来</span>
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">
                  VoiceGrow 管理中心
                </h2>
                <p className="text-orange-100 max-w-md">
                  声伴成长语音学习平台 — 管理故事、音乐和英语学习内容
                </p>
              </div>

              {/* Sound wave animation */}
              <div className="hidden lg:flex items-center gap-4">
                <div className="flex flex-col items-center gap-2">
                  <div className="w-16 h-16 rounded-2xl bg-white/20 backdrop-blur flex items-center justify-center">
                    <Volume2 className="w-7 h-7 text-white" />
                  </div>
                </div>
                <div className="soundwave scale-125">
                  <span></span>
                  <span></span>
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="总内容数"
            value={stats?.total_contents ?? 0}
            icon={FileText}
            color="text-orange-600"
            bgColor="bg-orange-50"
            trend={12}
            href="/contents"
          />
          <StatCard
            title="故事数量"
            value={stats?.story_count ?? 0}
            icon={BookOpen}
            color="text-rose-600"
            bgColor="bg-rose-50"
            href="/contents/stories"
          />
          <StatCard
            title="音乐数量"
            value={stats?.music_count ?? 0}
            icon={Music}
            color="text-violet-600"
            bgColor="bg-violet-50"
            href="/contents/music"
          />
          <StatCard
            title="英语单词"
            value={stats?.word_count ?? 0}
            icon={Languages}
            color="text-emerald-600"
            bgColor="bg-emerald-50"
            href="/english"
          />
        </div>

        {/* Quick Actions */}
        <div>
          <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5 text-orange-500" />
            快速操作
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <QuickAction
              title="添加故事"
              description="上传新的故事内容"
              icon={BookOpen}
              href="/contents/stories"
              color="bg-gradient-to-br from-rose-400 to-rose-600"
            />
            <QuickAction
              title="添加音乐"
              description="上传儿歌或音乐"
              icon={Music}
              href="/contents/music"
              color="bg-gradient-to-br from-violet-400 to-violet-600"
            />
            <QuickAction
              title="管理分类"
              description="整理内容分类体系"
              icon={Languages}
              href="/categories"
              color="bg-gradient-to-br from-emerald-400 to-emerald-600"
            />
          </div>
        </div>

        {/* Bottom Cards */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Recent Activity */}
          <div className="card p-5">
            <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-gray-400" />
              最近活动
            </h3>
            <div className="space-y-3">
              {[
                { action: "添加了新故事", item: "小红帽", time: "2分钟前", bg: "bg-rose-50", text: "text-rose-600" },
                { action: "更新了音乐", item: "小星星", time: "15分钟前", bg: "bg-violet-50", text: "text-violet-600" },
                { action: "添加了单词", item: "Apple", time: "1小时前", bg: "bg-emerald-50", text: "text-emerald-600" },
              ].map((activity, index) => (
                <div key={index} className="flex items-center gap-3 p-3 rounded-xl hover:bg-stone-50 transition-colors">
                  <div className={`w-10 h-10 rounded-lg ${activity.bg} ${activity.text} flex items-center justify-center font-bold text-sm`}>
                    {activity.item[0]}
                  </div>
                  <div className="flex-1">
                    <p className="text-gray-700 font-medium text-sm">{activity.action}</p>
                    <p className="text-xs text-gray-400">{activity.item}</p>
                  </div>
                  <span className="text-xs text-gray-400">{activity.time}</span>
                </div>
              ))}
            </div>
          </div>

          {/* System Status */}
          <div className="card p-5">
            <h3 className="font-bold text-gray-800 mb-4 flex items-center gap-2">
              <Zap className="w-5 h-5 text-green-500" />
              系统状态
            </h3>
            <div className="space-y-3">
              {[
                { name: "服务器状态", status: "正常运行", online: true },
                { name: "数据库连接", status: "已连接", online: true },
                { name: "存储服务", status: "MinIO 可用", online: true },
              ].map((service, index) => (
                <div key={index} className="flex items-center justify-between p-3 rounded-xl bg-stone-50">
                  <span className="text-gray-600 font-medium text-sm">{service.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-500">{service.status}</span>
                    <div className={`w-2 h-2 rounded-full ${service.online ? "bg-green-500" : "bg-red-500"}`} />
                  </div>
                </div>
              ))}
            </div>

            {isLoading && (
              <div className="mt-4 p-3 rounded-xl bg-orange-50 text-orange-600 text-sm flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-orange-600 border-t-transparent rounded-full animate-spin" />
                加载统计数据中...
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Dashboard;
