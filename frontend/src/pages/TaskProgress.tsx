import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertCircle, ArrowRight, CheckCircle2, Circle, LoaderCircle } from 'lucide-react';

import { api } from '@/api/client';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';

type Status = 'pending' | 'parsing' | 'locating' | 'composing' | 'outline_review' | 'done' | 'failed' | 'cancelled';

type AgentId =
  | 'parser'
  | 'locator'
  | 'requirements'
  | 'composer';

const agentMeta: Array<{ id: AgentId; name: string; desc: string }> = [
  { id: 'parser', name: 'Parser', desc: '文档结构提取' },
  { id: 'locator', name: 'Locator', desc: '关键章节定位' },
  { id: 'requirements', name: 'Requirements', desc: '招标要求抽取' },
  { id: 'composer', name: 'Composer', desc: '目录编排' },
];

function getPipelineProgress(status: Status, progress: number) {
  if (status === 'failed' || status === 'cancelled') return 0;
  if (status === 'done') return agentMeta.length;
  if (status === 'outline_review') return 4;
  if (status === 'parsing') return 1;
  if (status === 'locating') return 2;
  if (status === 'composing') {
    if (progress >= 80) return 4;
    return 3;
  }
  return 0;
}

function getPipelineProgressByNode(currentNode?: string | null) {
  if (!currentNode) return null;
  const nodeToAgent: Record<string, AgentId | 'done'> = {
    parser: 'parser',
    locator: 'locator',
    title: 'requirements',
    requirement_extractor: 'requirements',
    composer: 'composer',
    done: 'done',
  };
  const order: Array<AgentId | 'done'> = ['parser', 'locator', 'requirements', 'composer', 'done'];
  const agentId = nodeToAgent[currentNode] || currentNode;
  const idx = order.indexOf(agentId as AgentId | 'done');
  if (idx < 0) return null;
  if (agentId === 'done') return agentMeta.length;
  return Math.max(0, Math.min(agentMeta.length, idx));
}

function displayProgressPercent(status: Status, completedAgents: number, backendProgress: number) {
  if (status === 'done') return 100;
  if (status === 'outline_review') return Math.round((4 / agentMeta.length) * 100);
  if (status === 'failed' || status === 'cancelled') return backendProgress || 0;
  const clamped = Math.max(0, Math.min(agentMeta.length, completedAgents));
  return Math.round((clamped / agentMeta.length) * 100);
}

const TaskProgress: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [status, setStatus] = useState<Status>('pending');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [currentNode, setCurrentNode] = useState<string>('');
  const [isCancelling, setIsCancelling] = useState(false);
  const [stepTimes, setStepTimes] = useState<Record<string, number>>({});

  const completedAgents = useMemo(() => {
    const byNode = getPipelineProgressByNode(currentNode);
    if (byNode !== null) return byNode;
    return getPipelineProgress(status, progress);
  }, [status, progress, currentNode]);
  const visibleProgress = useMemo(
    () => displayProgressPercent(status, completedAgents, progress),
    [status, completedAgents, progress],
  );
  const totalSeconds = useMemo(() => {
    const vals = [
      stepTimes.parsing || 0,
      stepTimes.locating || 0,
      stepTimes.graph_total || 0,
    ];
    return vals.reduce((a, b) => a + b, 0);
  }, [stepTimes]);
  const safeMessage = useMemo(() => {
    if (status === 'pending') return '任务已创建，准备开始...';
    if (status === 'parsing') return '正在解析招标文件结构...';
    if (status === 'locating') return '正在定位关键章节与评分要求...';
    if (status === 'composing') {
      if (progress >= 80) return '正在生成目录与章节草稿...';
      return '正在编排投标书目录...';
    }
    if (status === 'outline_review') return '目录草稿已生成，请确认目录后再匹配素材';
    if (status === 'done') return '处理完成，正在跳转结果页...';
    if (status === 'failed') return '任务失败，请查看下方错误信息';
    if (status === 'cancelled') return '任务已取消';
    return '处理中...';
  }, [status, progress]);

  useEffect(() => {
    if (!projectId) return;
    let isMounted = true;

    const poll = async () => {
      try {
        const res = await api.get<{ status: Status; progress: number; message: string; error?: string; current_node?: string; step_times?: Record<string, number> }>(
          `/projects/${projectId}/status`,
        );
        if (!isMounted) return;

        setStatus(res.data.status);
        setProgress(res.data.progress);
        setError(res.data.error || '');
        setCurrentNode(res.data.current_node || '');
        setStepTimes(res.data.step_times || {});

        if (res.data.status === 'done' || res.data.status === 'outline_review') {
          setTimeout(() => navigate(`/outline/${projectId}`), 700);
        }
        if (res.data.status === 'cancelled') {
          setTimeout(() => navigate('/new'), 700);
        }
      } catch (err: any) {
        if (!isMounted) return;
        if (err?.response?.status === 404) {
          setStatus('failed');
          setError('任务不存在或已失效，请返回新建项目重新上传。');
          return;
        }
        setStatus('failed');
        setError(err?.response?.data?.message || '获取任务状态失败');
      }
    };

    poll();
    const timer = setInterval(poll, 1800);
    return () => {
      isMounted = false;
      clearInterval(timer);
    };
  }, [projectId, navigate]);

  const handleCancel = async () => {
    if (!projectId || isCancelling) return;
    setIsCancelling(true);
    try {
      await api.post(`/projects/${projectId}/cancel`);
    } catch (err: any) {
      setError(err?.response?.data?.message || '取消失败');
      setIsCancelling(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-xl font-semibold text-neutral-900">执行解析任务</h1>
            <p className="text-sm text-neutral-500 mt-1">{safeMessage}</p>
          </div>
          <div className="text-3xl font-semibold text-blue-700">{visibleProgress}%</div>
        </div>
        <Progress value={visibleProgress} className="h-2" />

        {!['done', 'outline_review', 'failed', 'cancelled'].includes(status) && (
          <div className="mt-4 flex justify-end">
            <Button variant="destructive" size="sm" onClick={handleCancel} disabled={isCancelling}>
              {isCancelling ? '取消中...' : '取消任务'}
            </Button>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">执行 Agent</h2>
          <div className="text-sm text-neutral-500">{completedAgents}/{agentMeta.length} 已完成</div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {agentMeta.map((item, idx) => {
            const done = idx < completedAgents;
            const active = idx === completedAgents && completedAgents < agentMeta.length && status !== 'failed';
            return (
              <div
                key={item.id}
                className={cn(
                  'rounded-lg border p-3',
                  done && 'bg-emerald-50 border-emerald-200',
                  active && 'bg-blue-50 border-blue-200',
                  !done && !active && 'bg-neutral-50 border-neutral-200',
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="font-medium text-sm">{item.name}</div>
                  {done ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  ) : active ? (
                    <LoaderCircle className="w-4 h-4 text-blue-600 animate-spin" />
                  ) : (
                    <Circle className="w-4 h-4 text-neutral-400" />
                  )}
                </div>
                <div className="text-xs text-neutral-500 mt-1">{item.desc}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-4 rounded-md border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-700">
          总耗时: {totalSeconds > 0 ? `${totalSeconds.toFixed(1)} 秒` : '处理中'}
        </div>
      </Card>

      {status === 'failed' && (
        <Alert variant="destructive">
          <AlertCircle className="w-4 h-4" />
          <AlertTitle>任务失败</AlertTitle>
          <AlertDescription>{error || '系统处理失败，请重试。'}</AlertDescription>
        </Alert>
      )}

      {(status === 'done' || status === 'outline_review') && (
        <div className="flex justify-end">
          <Button onClick={() => navigate(`/outline/${projectId}`)}>
            {status === 'outline_review' ? '确认目录' : '查看结果'} <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>
      )}
    </div>
  );
};

export default TaskProgress;
