import React from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Music, Languages, FileText } from "lucide-react";
import { Layout } from "../components/layout";
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui";
import { statsApi } from "../api";

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ElementType;
  color: string;
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon: Icon, color }) => (
  <Card>
    <CardHeader className="flex flex-row items-center justify-between pb-2">
      <CardTitle className="text-sm font-medium text-gray-500">{title}</CardTitle>
      <Icon className={`h-5 w-5 ${color}`} />
    </CardHeader>
    <CardContent>
      <div className="text-3xl font-bold">{value}</div>
    </CardContent>
  </Card>
);

const Dashboard: React.FC = () => {
  const { data: stats, isLoading } = useQuery({
    queryKey: ["stats"],
    queryFn: statsApi.get,
  });

  return (
    <Layout title="仪表盘">
      <div className="space-y-6">
        {/* Stats Grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="总内容数"
            value={stats?.total_contents ?? 0}
            icon={FileText}
            color="text-primary-600"
          />
          <StatCard
            title="故事数量"
            value={stats?.story_count ?? 0}
            icon={BookOpen}
            color="text-orange-500"
          />
          <StatCard
            title="音乐数量"
            value={stats?.music_count ?? 0}
            icon={Music}
            color="text-purple-500"
          />
          <StatCard
            title="英语单词"
            value={stats?.word_count ?? 0}
            icon={Languages}
            color="text-green-500"
          />
        </div>

        {/* Welcome Message */}
        <Card>
          <CardHeader>
            <CardTitle>欢迎使用 VoiceGrow 管理后台</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-gray-600">
              这是 VoiceGrow 声伴成长语音学习平台的内容管理系统。
              您可以在这里管理故事、音乐和英语学习内容。
            </p>
            {isLoading && (
              <p className="mt-2 text-sm text-gray-400">加载统计数据中...</p>
            )}
          </CardContent>
        </Card>
      </div>
    </Layout>
  );
};

export default Dashboard;
