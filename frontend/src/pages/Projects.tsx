import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, Download, FileText, FolderClock, LoaderCircle, RefreshCw, Search, ShieldAlert, Trash2 } from 'lucide-react'
import { apiUrl, tenderAPI, type ProjectListItem } from '@/api/client'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const statusLabel: Record<string, string> = {
  pending: '等待中',
  parsing: '解析中',
  locating: '定位中',
  composing: '生成中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const formatDate = (value?: string | null) => {
  if (!value) return '未知时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const Projects: React.FC = () => {
  const [projects, setProjects] = useState<ProjectListItem[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ProjectListItem | null>(null)
  const [deletingId, setDeletingId] = useState('')

  const loadProjects = async () => {
    setLoading(true)
    setError('')
    try {
      const rows = await tenderAPI.listProjects({ limit: 300 })
      setProjects(rows)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '读取项目列表失败，请确认后端服务已启动')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProjects()
  }, [])

  const handleDeleteProject = async () => {
    if (!deleteTarget || deletingId) return
    const projectId = deleteTarget.id
    setDeletingId(projectId)
    setError('')
    try {
      await tenderAPI.deleteProject(projectId)
      setProjects((rows) => rows.filter((item) => item.id !== projectId))
      setDeleteTarget(null)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '项目删除失败，请稍后重试')
    } finally {
      setDeletingId('')
    }
  }

  const filteredProjects = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    if (!keyword) return projects
    return projects.filter((item) => {
      const haystack = [item.project_name, item.filename, item.purchaser, item.company_name, item.id]
        .join(' ')
        .toLowerCase()
      return haystack.includes(keyword)
    })
  }, [projects, query])

  const doneCount = projects.filter((item) => item.status === 'done').length
  const docxCount = projects.filter((item) => item.has_docx).length

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 p-6 text-white shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-blue-100 ring-1 ring-white/15">
              <FolderClock className="h-3.5 w-3.5" />
              历史生成记录
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">项目列表</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300">
              这里会读取之前生成过的目录和结果文件，可以继续查看目录、风险报告或下载已渲染的投标文件。
            </p>
          </div>
          <div className="flex w-full gap-2 lg:w-[460px]">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索项目名称 / 文件名 / 采购方"
                className="h-10 border-white/15 bg-white/10 pl-9 text-white placeholder:text-slate-400"
              />
            </div>
            <Button type="button" onClick={loadProjects} disabled={loading} className="h-10 bg-blue-400 text-slate-950 hover:bg-blue-300">
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        </div>
      </div>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>全部项目</CardTitle>
            <CardDescription>从 data/output 自动恢复</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold">{projects.length}</div></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>已完成</CardTitle>
            <CardDescription>可查看目录或重新导出</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold">{doneCount}</div></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>已有 DOCX</CardTitle>
            <CardDescription>已经渲染过投标文件</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold">{docxCount}</div></CardContent>
        </Card>
      </div>

      <Card className="border-slate-200 bg-white">
        <CardHeader>
          <CardTitle>生成过的目录</CardTitle>
          <CardDescription>共 {filteredProjects.length} 条记录，按最后更新时间倒序排列</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-slate-100">
            {filteredProjects.map((item) => (
              <div key={item.id} className="grid gap-4 px-5 py-4 lg:grid-cols-[1fr_260px]">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={item.status === 'done' ? `/outline/${item.id}` : `/progress/${item.id}`} className="truncate text-base font-semibold text-slate-950 hover:text-blue-700">
                      {item.project_name || item.filename}
                    </Link>
                    <Badge variant={item.status === 'done' ? 'default' : item.status === 'failed' ? 'destructive' : 'secondary'}>
                      {statusLabel[item.status] || item.status}
                    </Badge>
                    {item.has_docx && <Badge variant="outline">DOCX</Badge>}
                  </div>
                  <div className="truncate text-sm text-slate-500">源文件：{item.filename}</div>
                  <div className="flex flex-wrap gap-4 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5" />{formatDate(item.updated_at || item.created_at)}</span>
                    <span className="inline-flex items-center gap-1"><FileText className="h-3.5 w-3.5" />目录节点 {item.outline_count}</span>
                    <span>正文 {item.generated_section_count}</span>
                    <span className="inline-flex items-center gap-1"><ShieldAlert className="h-3.5 w-3.5" />风险 {item.compliance_issue_count + item.consistency_conflict_count}</span>
                  </div>
                  {item.error && <div className="text-xs text-red-600">{item.error}</div>}
                </div>
                <div className="flex flex-wrap items-center justify-start gap-2 lg:justify-end">
                  {item.status === 'done' ? (
                    <Button asChild variant="outline"><Link to={`/outline/${item.id}`}>查看目录</Link></Button>
                  ) : (
                    <Button asChild variant="outline"><Link to={`/progress/${item.id}`}>查看进度</Link></Button>
                  )}
                  {item.has_result && (
                    <Button asChild variant="default">
                      <a href={apiUrl(`/projects/${item.id}/download`)} target="_blank" rel="noreferrer">
                        <Download className="h-4 w-4" />下载
                      </a>
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    className="text-red-600 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                    onClick={() => setDeleteTarget(item)}
                    disabled={Boolean(deletingId)}
                  >
                    {deletingId === item.id ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                    删除
                  </Button>
                </div>
              </div>
            ))}
            {!loading && filteredProjects.length === 0 && (
              <div className="px-5 py-12 text-center text-sm text-slate-500">还没有历史项目，上传招标文件后会自动出现在这里。</div>
            )}
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && !deletingId && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除这个项目？</AlertDialogTitle>
            <AlertDialogDescription>
              将永久删除“{deleteTarget?.project_name || deleteTarget?.filename || ''}”的源文件、解析结果和已导出的 Word，知识库素材不会受影响。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(deletingId)}>取消</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={(event) => {
                event.preventDefault()
                void handleDeleteProject()
              }}
              disabled={Boolean(deletingId)}
            >
              {deletingId ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {deletingId ? '删除中...' : '确认删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export default Projects
