import React, { useState, useRef, useEffect, useCallback } from 'react'
import { ChevronRight, ChevronDown, GripVertical, Plus, Trash2, BadgeInfo } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { OutlineNode, EditorAction, isMoveValid, isEmptyOutlineNode } from '@/lib/outline-editor'

type DropPosition = 'before' | 'after' | 'inside' | null

type OutlineEditorProps = {
  nodes: OutlineNode[]
  selectedUid: string | null
  onSelect: (uid: string | null) => void
  dispatch: React.Dispatch<EditorAction>
}

/**
 * 可编辑名称（双击行内编辑）
 */
function EditableName({ name, nodeUid, onSelect, onRename }: {
  name: string; nodeUid: string
  onSelect: (uid: string) => void; onRename: (uid: string, name: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(name)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => { if (editing && ref.current) { ref.current.focus(); ref.current.select() } }, [editing])

  if (editing) {
    return (
      <Input ref={ref} value={val} className="h-6 text-sm py-0 px-1 flex-1 min-w-0"
        onChange={e => setVal(e.target.value)}
        onBlur={() => { if (val.trim()) onRename(nodeUid, val.trim()); setEditing(false) }}
        onKeyDown={e => {
          if (e.key === 'Enter') { if (val.trim()) onRename(nodeUid, val.trim()); setEditing(false) }
          if (e.key === 'Escape') setEditing(false)
        }}
        onPointerDown={e => e.stopPropagation()}
      />
    )
  }
  return (
    <span
      className="flex-1 text-sm select-none truncate min-w-0 cursor-pointer"
      title={name}
      aria-label={name}
      onDoubleClick={() => { setVal(name); setEditing(true) }}
      onClick={() => onSelect(nodeUid)}
    >{name}</span>
  )
}

/**
 * 主编辑器组件 - 使用原生HTML5拖拽
 */
function OutlineEditor({ nodes, selectedUid, onSelect, dispatch }: OutlineEditorProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // 拖拽状态 — 用 ref 保证实时读取
  const [dragUid, setDragUid] = useState<string | null>(null)
  const [overUid, setOverUid] = useState<string | null>(null)
  const [dropPos, setDropPos] = useState<DropPosition>(null)
  const stateRef = useRef({ dragUid: null as string|null, overUid: null as string|null, dropPos: null as DropPosition })
  const nodesRef = useRef(nodes)
  nodesRef.current = nodes

  // 展开全部
  useEffect(() => {
    const s = new Set<string>()
    const walk = (ns: OutlineNode[]) => ns.forEach(n => { s.add(n.uid); walk(n.children) })
    walk(nodes)
    setExpanded(s)
  }, [nodes])

  const toggle = useCallback((uid: string) => {
    setExpanded(prev => { const n = new Set(prev); n.has(uid) ? n.delete(uid) : n.add(uid); return n })
  }, [])

  // ---- 拖拽回调 ----
  const onDragStart = useCallback((uid: string, e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', uid)  // 必须设置，否则浏览器打开新标签
    stateRef.current.dragUid = uid
    setDragUid(uid)
  }, [])

  const onDragOver = useCallback((uid: string, e: React.DragEvent) => {
    e.preventDefault()               // 必须，否则不允许 drop
    e.dataTransfer.dropEffect = 'move'

    const src = stateRef.current.dragUid
    if (!src || src === uid) return

    const rect = e.currentTarget.getBoundingClientRect()
    const ry = (e.clientY - rect.top) / rect.height
    const rx = (e.clientX - rect.left) / rect.width

    let pos: DropPosition = 'before'
    if (ry > 0.66) pos = 'after'
    else if (ry >= 0.33 && rx > 0.6) pos = 'inside'

    // 只在变化时更新
    if (stateRef.current.overUid !== uid || stateRef.current.dropPos !== pos) {
      stateRef.current.overUid = uid
      stateRef.current.dropPos = pos
      setOverUid(uid)
      setDropPos(pos)
    }
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const { dragUid: src, overUid: tgt, dropPos: pos } = stateRef.current
    if (src && tgt && pos && src !== tgt) {
      if (isMoveValid(nodesRef.current, src, tgt, pos)) {
        dispatch({ type: 'MOVE', sourceUid: src, targetUid: tgt, position: pos })
      }
    }
    cleanup()
  }, [dispatch])

  const onDragEnd = useCallback(() => cleanup(), [])

  const cleanup = useCallback(() => {
    stateRef.current = { dragUid: null, overUid: null, dropPos: null }
    setDragUid(null)
    setOverUid(null)
    setDropPos(null)
  }, [])

  // ---- 其他操作 ----
  const rename = useCallback((uid: string, name: string) => dispatch({ type: 'RENAME', uid, name }), [dispatch])
  const addChild = useCallback((uid: string) => dispatch({ type: 'ADD_CHILD', parentUid: uid }), [dispatch])
  const del = useCallback((uid: string) => {
    if (confirm('确定要删除该章节及其所有子章节吗？')) dispatch({ type: 'DELETE', uid })
  }, [dispatch])

  // ---- 递归渲染 ----
  const renderNode = (node: OutlineNode, depth: number): React.ReactNode => {
    if (isEmptyOutlineNode(node.name)) {
      return <React.Fragment key={node.uid}>{node.children.map(c => renderNode(c, depth))}</React.Fragment>
    }

    const hasKids = node.children.length > 0
    const isOpen = expanded.has(node.uid)
    const isSel = selectedUid === node.uid
    const isDragging = dragUid === node.uid
    const isOver = overUid === node.uid

    let border = ''
    if (isOver && dropPos === 'before') border = 'border-t-[2px] border-t-blue-500'
    else if (isOver && dropPos === 'after') border = 'border-b-[2px] border-b-blue-500'
    else if (isOver && dropPos === 'inside') border = 'ring-2 ring-blue-400 bg-blue-50/60 rounded'

    return (
      <React.Fragment key={node.uid}>
        {/* 节点行 */}
        <div
          className={cn(
            'group relative flex items-center gap-1 py-1.5 pr-1 hover:bg-neutral-50 transition-colors',
            isSel && !isDragging && 'bg-blue-50 hover:bg-blue-50',
            isDragging && 'opacity-30',
            border
          )}
          style={{ paddingLeft: depth * 20 + 8 }}
          title={node.name}
          draggable="true"
          onDragStart={e => onDragStart(node.uid, e)}
          onDragOver={e => onDragOver(node.uid, e)}
          onDrop={onDrop}
          onDragEnd={onDragEnd}
        >
          {/* 手柄图标 */}
          <GripVertical size={14} className="text-neutral-300 group-hover:text-neutral-500 shrink-0" />

          {/* 展开折叠 */}
          {hasKids ? (
            <button className="shrink-0 p-0.5 hover:bg-neutral-200 rounded"
              onPointerDown={e => e.stopPropagation()}
              onClick={() => toggle(node.uid)}
            >
              {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : <span className="w-5 shrink-0" />}

          {/* 编号 */}
          <span className="text-[11px] text-neutral-400 min-w-[26px] shrink-0 font-mono">{node.id}</span>

          {/* 名称 */}
          <EditableName name={node.name} nodeUid={node.uid} onSelect={onSelect} onRename={rename} />

          {/* 标签 */}
          {node.required && <Badge className="text-[10px] h-4 px-1 bg-red-50 text-red-700 border-red-200 shrink-0 ml-1">必填</Badge>}
          {node.has_template && <Badge className="text-[10px] h-4 px-1 bg-blue-50 text-blue-700 border-blue-200 shrink-0 ml-1">范本</Badge>}

          {/* hover操作 */}
          <div className="hidden group-hover:flex absolute right-1 top-1/2 -translate-y-1/2 gap-0.5 rounded bg-white/95 shadow-sm ring-1 ring-neutral-200">
            {node.level < 3 && (
              <button className="p-0.5 rounded hover:bg-green-100 text-neutral-400 hover:text-green-600"
                onPointerDown={e => e.stopPropagation()}
                onClick={() => addChild(node.uid)} title="添加子章节"
              ><Plus size={13} /></button>
            )}
            <button className="p-0.5 rounded hover:bg-red-100 text-neutral-400 hover:text-red-600"
              onPointerDown={e => e.stopPropagation()}
              onClick={() => del(node.uid)} title="删除"
            ><Trash2 size={13} /></button>
          </div>
        </div>

        {/* 子节点 */}
        {hasKids && isOpen && node.children.map(c => renderNode(c, depth + 1))}
      </React.Fragment>
    )
  }

  return (
    <div className="h-full overflow-auto py-1.5">
      {nodes.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-[300px] text-neutral-400">
          <BadgeInfo size={48} className="mb-2 opacity-50" />
          <p>暂无目录数据</p>
        </div>
      ) : nodes.map(n => renderNode(n, 0))}
    </div>
  )
}

export { OutlineEditor }
