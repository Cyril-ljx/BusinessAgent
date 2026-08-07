import { Database, FileText, Paperclip, PenLine, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { OutlineNode } from '@/lib/outline-editor'

export type MaterialItem = {
  source: 'certificate' | 'tech_section' | 'manual'
  category?: string
  chapter_id?: string
  max_count?: number
  note?: string
}

export type MaterialAssignment = {
  node_id: string
  node_name: string
  materials: MaterialItem[]
}

type MaterialPanelProps = {
  selectedNode: OutlineNode | null
  assignments: MaterialAssignment[]
  onRemove?: (nodeId: string, materialIndex: number) => void
}

function getMaterialMeta(material: MaterialItem) {
  if (material.source === 'certificate') {
    return {
      icon: Database,
      title: `证书库 - ${material.category || '未分类'}`,
      desc: `最多 ${material.max_count || 1} 张`,
      badge: '证书',
      className: 'bg-blue-50 text-blue-700 border-blue-200',
    }
  }
  if (material.source === 'tech_section') {
    return {
      icon: FileText,
      title: `技术章节 - ${material.chapter_id || '-'}`,
      desc: '从技术母版复制整段内容',
      badge: '技术',
      className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    }
  }
  return {
    icon: PenLine,
    title: material.note || '请业务人员手填',
    desc: '需要人工补充或确认',
    badge: '手填',
    className: 'bg-amber-50 text-amber-700 border-amber-200',
  }
}

export function MaterialPanel({ selectedNode, assignments, onRemove }: MaterialPanelProps) {
  const current = selectedNode
    ? assignments.find(item => String(item.node_id) === String(selectedNode.id))
    : null
  const materials = current?.materials || []

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <Paperclip className="w-4 h-4 text-blue-600" />
          <h3 className="font-medium text-neutral-900">素材分配</h3>
        </div>
        <p className="text-xs text-neutral-500 mt-1">查看当前章节匹配到的知识库素材</p>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {!selectedNode ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-neutral-400">
            <Paperclip className="w-8 h-8 mb-2 opacity-50" />
            <p className="text-sm">请选择左侧目录章节</p>
          </div>
        ) : materials.length === 0 ? (
          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium text-neutral-900">
                {selectedNode.id} {selectedNode.name}
              </p>
              <p className="text-xs text-neutral-500 mt-1">当前章节暂无素材分配</p>
            </div>
            <div className="rounded-lg border border-dashed p-4 text-sm text-neutral-500 bg-neutral-50">
              后续可在这里手动添加证书、技术章节或手填说明。
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <p className="text-sm font-medium text-neutral-900">
                {selectedNode.id} {selectedNode.name}
              </p>
              <p className="text-xs text-neutral-500 mt-1">
                已分配 {materials.length} 个素材
              </p>
            </div>

            {materials.map((material, index) => {
              const meta = getMaterialMeta(material)
              const Icon = meta.icon
              return (
                <div key={`${material.source}-${index}`} className="rounded-lg border bg-white p-3 shadow-sm">
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5 rounded-md bg-neutral-100 p-1.5">
                      <Icon className="w-4 h-4 text-neutral-600" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className={meta.className}>{meta.badge}</Badge>
                        <span className="text-xs text-neutral-400">#{index + 1}</span>
                      </div>
                      <p className="text-sm font-medium text-neutral-900 mt-1 break-words">{meta.title}</p>
                      <p className="text-xs text-neutral-500 mt-1">{meta.desc}</p>
                    </div>
                    {onRemove && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 text-neutral-400 hover:text-red-600 hover:bg-red-50"
                        onClick={() => onRemove(selectedNode.id, index)}
                        title="移除该素材"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
