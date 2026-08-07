import React, { useState, useEffect } from 'react'
import { Save, Trash2, Download, Upload, FolderPlus, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { api } from '@/api/client'
import { OutlineNode, EditorAction, removeUidsFromNodes, addUidsToNodes } from '@/lib/outline-editor'

type TemplateItem = {
  id: string
  name: string
  category: string
  chapter_count: number
  created_at: string
}

type TemplatePanelProps = {
  projectId: string
  currentOutline: OutlineNode[]
  dispatch: React.Dispatch<EditorAction>
}

export function TemplatePanel({ projectId, currentOutline, dispatch }: TemplatePanelProps) {
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [isSaveDialogOpen, setIsSaveDialogOpen] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [templateCategory, setTemplateCategory] = useState('通用')
  const [isLoading, setIsLoading] = useState(false)

  // 加载模板列表
  const loadTemplates = async () => {
    try {
      const res = await api.get<TemplateItem[]>('/templates')
      setTemplates(res.data)
    } catch (error) {
      console.error('加载模板列表失败:', error)
    }
  }

  // 保存为模板
  const handleSaveTemplate = async () => {
    if (!templateName.trim()) return
    setIsLoading(true)
    try {
      const outlineWithoutUids = removeUidsFromNodes(currentOutline)
      await api.post('/templates', {
        name: templateName.trim(),
        category: templateCategory.trim() || '通用',
        outline: outlineWithoutUids,
      })
      setIsSaveDialogOpen(false)
      setTemplateName('')
      setTemplateCategory('通用')
      loadTemplates()
    } catch (error) {
      console.error('保存模板失败:', error)
      alert('保存失败，请重试')
    } finally {
      setIsLoading(false)
    }
  }

  // 应用模板
  const handleApplyTemplate = async (template: TemplateItem) => {
    if (!confirm(`确定要应用模板「${template.name}」吗？当前目录会被替换。`)) return
    try {
      const res = await api.post(`/projects/${projectId}/apply-template`, {
        template_id: template.id,
      })
      // 从后端获取应用后的outline，加上uid后更新前端
      const outlineWithUids = addUidsToNodes(res.data.outline)
      dispatch({ type: 'LOAD', payload: outlineWithUids })
    } catch (error) {
      console.error('应用模板失败:', error)
      alert('应用失败，请重试')
    }
  }

  // 删除模板
  const handleDeleteTemplate = async (templateId: string) => {
    try {
      await api.delete(`/templates/${templateId}`)
      loadTemplates()
    } catch (error) {
      console.error('删除模板失败:', error)
      alert('删除失败，请重试')
    }
  }

  // 导出当前目录为JSON文件（下载到本地）
  const handleExportJSON = () => {
    const outlineWithoutUids = removeUidsFromNodes(currentOutline)
    const dataStr = JSON.stringify(outlineWithoutUids, null, 2)
    const blob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '目录模板.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  // 导入JSON文件
  const handleImportJSON = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const imported = JSON.parse(event.target?.result as string)
        const outlineWithUids = Array.isArray(imported) ? addUidsToNodes(imported) : addUidsToNodes(imported.outline || [])
        dispatch({ type: 'LOAD', payload: outlineWithUids })
      } catch (error) {
        alert('导入失败，请确保文件是有效的JSON格式。')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  useEffect(() => {
    loadTemplates()
  }, [])

  return (
    <div className="h-full flex flex-col p-4 gap-4">
      {/* 操作按钮组 */}
      <div className="flex gap-2">
        <Button className="flex-1 gap-1.5" onClick={() => setIsSaveDialogOpen(true)}>
          <Save size={14} /> 保存为模板
        </Button>
        <Button variant="secondary" className="flex-1 gap-1.5" onClick={handleExportJSON}>
          <Download size={14} /> 导出JSON
        </Button>
      </div>
      <div>
        <label className="inline-flex items-center justify-center w-full h-9 rounded-md text-sm font-medium bg-white border border-input hover:bg-accent hover:text-accent-foreground cursor-pointer gap-1.5">
          <Upload size={14} /> 导入JSON模板
          <input type="file" accept=".json" className="hidden" onChange={handleImportJSON} />
        </label>
      </div>

      {/* 模板列表 */}
      <Card className="flex-1 overflow-hidden">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <FolderPlus className="h-4 w-4 text-blue-600" />
            <CardTitle className="text-base">模板库</CardTitle>
          </div>
          <CardDescription className="text-xs">点击「应用」替换当前目录</CardDescription>
        </CardHeader>
        <Separator />
        <CardContent className="p-0">
          <ScrollArea className="h-[350px]">
            {templates.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-neutral-400 text-sm">
                <AlertCircle size={24} className="mb-2 opacity-50" />
                <p>暂无模板，试试「保存为模板」或「导入JSON」</p>
              </div>
            ) : (
              <div className="divide-y">
                {templates.map((t) => (
                  <div key={t.id} className="p-3 hover:bg-neutral-50">
                    <div className="flex justify-between items-start mb-1">
                      <span className="text-sm font-medium truncate flex-1 mr-2">{t.name}</span>
                      <div className="flex gap-1 shrink-0">
                        <Badge variant="outline" className="text-[10px] h-4 px-1">{t.category}</Badge>
                        <Badge variant="secondary" className="text-[10px] h-4 px-1">{t.chapter_count}章</Badge>
                      </div>
                    </div>
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-xs text-neutral-400">
                        {t.created_at ? new Date(t.created_at).toLocaleDateString('zh-CN') : ''}
                      </span>
                      <div className="flex gap-1">
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button size="icon" variant="ghost" className="h-7 w-7 text-red-500 hover:text-red-700 hover:bg-red-50">
                              <Trash2 size={14} />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>确定删除模板？</AlertDialogTitle>
                              <AlertDialogDescription>
                                模板「{t.name}」将会被永久删除，无法恢复。
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction onClick={() => handleDeleteTemplate(t.id)} className="bg-red-600 hover:bg-red-700">
                                删除
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 text-xs gap-1"
                          onClick={() => handleApplyTemplate(t)}
                        >
                          <Download size={12} /> 应用
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {/* 保存模板弹窗 */}
      <Dialog open={isSaveDialogOpen} onOpenChange={setIsSaveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保存为模板</DialogTitle>
            <DialogDescription>将当前目录结构保存为模板，可在后续项目中直接使用。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="template-name">模板名称</Label>
              <Input id="template-name" placeholder="如：餐饮服务-技术文件模板" value={templateName} onChange={(e) => setTemplateName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="template-category">行业分类</Label>
              <Input id="template-category" placeholder="如：餐饮服务、物流仓储、事业单位" value={templateCategory} onChange={(e) => setTemplateCategory(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setIsSaveDialogOpen(false)}>取消</Button>
            <Button onClick={handleSaveTemplate} disabled={isLoading || !templateName.trim()}>
              {isLoading ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
