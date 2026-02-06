import React from "react";
import { Settings as SettingsIcon, Server, Database, Cloud, Volume2, Mic } from "lucide-react";
import { Layout } from "../../components/layout";
import { Badge } from "../../components/ui";

const Settings: React.FC = () => {
  return (
    <Layout title="系统设置">
      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-gray-600 to-gray-700 flex items-center justify-center shadow-lg">
            <SettingsIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-800">系统设置</h2>
            <p className="text-gray-500 text-sm">配置系统参数和服务状态</p>
          </div>
        </div>

        {/* Service Status */}
        <div className="card p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">服务状态</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Server */}
            <div className="flex items-center gap-4 p-4 bg-stone-50 rounded-xl">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-400 to-blue-500 flex items-center justify-center">
                <Server className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-gray-800">VoiceGrow Server</p>
                <p className="text-sm text-gray-500">WebSocket :4399</p>
              </div>
              <Badge variant="default">运行中</Badge>
            </div>

            {/* Database */}
            <div className="flex items-center gap-4 p-4 bg-stone-50 rounded-xl">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-500 flex items-center justify-center">
                <Database className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-gray-800">MySQL</p>
                <p className="text-sm text-gray-500">localhost:3306</p>
              </div>
              <Badge variant="default">已连接</Badge>
            </div>

            {/* MinIO */}
            <div className="flex items-center gap-4 p-4 bg-stone-50 rounded-xl">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center">
                <Cloud className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-gray-800">MinIO</p>
                <p className="text-sm text-gray-500">对象存储</p>
              </div>
              <Badge variant="default">已连接</Badge>
            </div>

            {/* ASR */}
            <div className="flex items-center gap-4 p-4 bg-stone-50 rounded-xl">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center">
                <Mic className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-gray-800">ASR 服务</p>
                <p className="text-sm text-gray-500">faster-whisper</p>
              </div>
              <Badge variant="default">就绪</Badge>
            </div>

            {/* TTS */}
            <div className="flex items-center gap-4 p-4 bg-stone-50 rounded-xl">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center">
                <Volume2 className="w-5 h-5 text-white" />
              </div>
              <div className="flex-1">
                <p className="font-medium text-gray-800">TTS 服务</p>
                <p className="text-sm text-gray-500">Azure Speech</p>
              </div>
              <Badge variant="default">就绪</Badge>
            </div>
          </div>
        </div>

        {/* System Info */}
        <div className="card p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">系统信息</h3>
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-stone-100">
              <span className="text-gray-500">系统版本</span>
              <span className="font-medium text-gray-800">v0.2.0</span>
            </div>
            <div className="flex justify-between py-2 border-b border-stone-100">
              <span className="text-gray-500">支持设备</span>
              <span className="font-medium text-gray-800">小爱音箱 Pro (LX06), Smart Speaker Pro (OH2P)</span>
            </div>
            <div className="flex justify-between py-2 border-b border-stone-100">
              <span className="text-gray-500">唤醒词</span>
              <span className="font-medium text-gray-800">小爱同学</span>
            </div>
            <div className="flex justify-between py-2 border-b border-stone-100">
              <span className="text-gray-500">API 端口</span>
              <span className="font-medium text-gray-800">HTTP :8000 / WebSocket :4399</span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-gray-500">客户端</span>
              <span className="font-medium text-gray-800">open-xiaoai (Rust)</span>
            </div>
          </div>
        </div>

        {/* Placeholder for future settings */}
        <div className="card p-6 border-2 border-dashed border-stone-200 bg-stone-50/50">
          <div className="text-center py-8">
            <SettingsIcon className="w-12 h-12 text-stone-300 mx-auto mb-3" />
            <p className="text-gray-500">更多设置功能开发中...</p>
            <p className="text-sm text-gray-400 mt-1">ASR 模型选择、TTS 语音配置、设备管理等</p>
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Settings;
