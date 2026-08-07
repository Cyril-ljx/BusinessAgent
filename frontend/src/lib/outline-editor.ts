
import { nanoid } from 'nanoid'

// 核心数据类型
export type OutlineNode = {
  id: string           // "1", "1.1", 展示用编号
  uid: string          // 唯一标识，编辑过程中不变
  name: string         // 章节名
  level: number        // 层级 1/2/3
  required: boolean    // 是否必填
  has_template: boolean // 是否有范本
  children: OutlineNode[]
  source?: string // 来源标记，例如 index_table 表示来自招标原文索引表
  description?: string // 章节描述，可选
  source_evidence?: string // 来源说明，可选
}

export type OutlineNodeWithoutUid = Omit<OutlineNode, 'uid' | 'children'> & {
  children: OutlineNodeWithoutUid[]
}

// 编辑器状态
export type EditorState = {
  outline: OutlineNode[]
  selectedUid: string | null
  history: OutlineNode[][]      // 撤销栈
  future: OutlineNode[][]       // 重做栈
  isDirty: boolean              // 是否有未保存改动
  saveStatus: 'idle' | 'saving' | 'saved' | 'failed' // 保存状态
}

// 操作类型
export type EditorAction =
  | { type: 'LOAD'; payload: OutlineNode[] }
  | { type: 'SELECT'; uid: string | null }
  | { type: 'RENAME'; uid: string; name: string }
  | { type: 'UPDATE_DESCRIPTION'; uid: string; description: string }
  | { type: 'ADD_CHILD'; parentUid: string | null } // null = 添加一级节点
  | { type: 'DELETE'; uid: string }
  | { type: 'MOVE'; sourceUid: string; targetUid: string; position: 'before' | 'after' | 'inside' }
  | { type: 'TOGGLE_REQUIRED'; uid: string }
  | { type: 'TOGGLE_TEMPLATE'; uid: string }
  | { type: 'RENUMBER' }
  | { type: 'UNDO' }
  | { type: 'REDO' }
  | { type: 'SAVE_START' }
  | { type: 'SAVE_SUCCESS' }
  | { type: 'SAVE_FAILED' }

/**
 * 工具函数：递归遍历所有节点
 */
export function traverseNodes(
  nodes: OutlineNode[],
  callback: (node: OutlineNode, parent: OutlineNode | null, index: number) => void,
  parent: OutlineNode | null = null
): void {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]
    callback(node, parent, i)
    if (node.children.length > 0) {
      traverseNodes(node.children, callback, node)
    }
  }
}

/**
 * 工具函数：查找节点和父节点
 */
export function findNode(
  nodes: OutlineNode[],
  uid: string
): { node: OutlineNode | null; parent: OutlineNode | null; index: number } {
  let result: { node: OutlineNode | null; parent: OutlineNode | null; index: number } = {
    node: null,
    parent: null,
    index: -1
  }

  traverseNodes(nodes, (node, parent, index) => {
    if (node.uid === uid) {
      result = { node, parent, index }
    }
  })

  return result
}

/**
 * 工具函数：深度克隆节点树
 */
export function cloneOutline(nodes: OutlineNode[]): OutlineNode[] {
  return nodes.map(node => ({
    ...node,
    children: cloneOutline(node.children)
  }))
}

/**
 * 工具函数：自动重新编号所有节点
 */
export function renumberNodes(nodes: OutlineNode[], parentId = ''): OutlineNode[] {
  return nodes.map((node, index) => {
    const newId = parentId ? `${parentId}.${index + 1}` : `${index + 1}`
    return {
      ...node,
      id: newId,
      level: parentId.split('.').length + 1,
      children: renumberNodes(node.children, newId)
    }
  })
}

/**
 * 工具函数：为后端返回的节点添加uid
 */
export function addUidsToNodes(nodes: OutlineNodeWithoutUid[]): OutlineNode[] {
  return nodes.flatMap(node => {
    const children = addUidsToNodes(node.children || [])
    if (isEmptyOutlineNode(node.name)) return children
    return [{
      ...node,
      uid: nanoid(),
      children
    }]
  })
}

/**
 * 工具函数：移除uid，用于保存到后端
 */
export function removeUidsFromNodes(nodes: OutlineNode[]): OutlineNodeWithoutUid[] {
  return nodes.flatMap(node => {
    const children = removeUidsFromNodes(node.children)
    if (isEmptyOutlineNode(node.name)) return children
    return [{
      id: node.id,
      name: node.name,
      level: node.level,
      required: node.required,
      has_template: node.has_template,
      children,
      source: node.source,
      description: node.description,
      source_evidence: node.source_evidence
    }]
  })
}

export function shouldDropOutlineNode(name?: string): boolean {
  return isEmptyOutlineNode(name) || isBodySentenceOutlineNode(name)
}

export function isEmptyOutlineNode(name?: string): boolean {
  return !(name || '').trim()
}

export function isBodySentenceOutlineNode(name?: string): boolean {
  const normalized = (name || '').replace(/\s+/g, '')
  if (!normalized) return false
  if (/^《.+》$/.test(normalized)) return true

  const bodyPhrases = [
    '签订方式', '电子签署', '法规资讯', '薪酬待遇', '工龄工资',
    '养老保险', '安全管理制度', '劳务人员', '员工情况'
  ]
  if (bodyPhrases.some(word => normalized.includes(word))) return true

  if (normalized.length < 16) return false
  if (normalized.length > 34) return true
  if (/[：:，,。；;！!？?]/.test(normalized)) return true

  const bodyWords = [
    '我司', '负责', '采用', '提供', '包含', '提高', '以及', '对于',
    '进行', '开展', '确保', '保证', '根据', '按照', '通过'
  ]
  return normalized.length >= 10 && bodyWords.some(word => normalized.includes(word))
}

/**
 * 工具函数：检查目标位置是否合法（禁止父节点拖到自己的子节点里，禁止超过3级）
 */
export function isMoveValid(
  outline: OutlineNode[],
  sourceUid: string,
  targetUid: string,
  position: 'before' | 'after' | 'inside'
): boolean {
  // 查找源节点和目标节点
  const { node: sourceNode } = findNode(outline, sourceUid)
  const { node: targetNode } = findNode(outline, targetUid)

  if (!sourceNode || !targetNode) return false

  // 禁止拖拽到自身
  if (sourceUid === targetUid) return false

  // 计算目标层级，如果是inside则层级+1
  const targetLevel = position === 'inside' ? targetNode.level + 1 : targetNode.level
  if (targetLevel > 3) return false // 最多3级

  // 检查目标节点是否在源节点的子树里（防止循环）
  let isInSubtree = false
  traverseNodes(sourceNode.children, (node) => {
    if (node.uid === targetUid) {
      isInSubtree = true
    }
  })
  if (isInSubtree) return false

  return true
}

/**
 * 核心Reducer
 */
export function outlineEditorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case 'LOAD': {
      return {
        ...state,
        outline: action.payload,
        history: [action.payload],
        future: [],
        isDirty: false,
        saveStatus: 'saved'
      }
    }

    case 'SELECT': {
      return {
        ...state,
        selectedUid: action.uid
      }
    }

    case 'RENAME': {
      const newOutline = cloneOutline(state.outline)
      const { node } = findNode(newOutline, action.uid)
      if (node && action.name.trim()) {
        node.name = action.name.trim()
      }
      return {
        ...state,
        outline: newOutline,
        history: [...state.history, newOutline],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'UPDATE_DESCRIPTION': {
      const newOutline = cloneOutline(state.outline)
      const { node } = findNode(newOutline, action.uid)
      if (node) {
        node.description = action.description
      }
      return {
        ...state,
        outline: newOutline,
        history: [...state.history, newOutline],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'ADD_CHILD': {
      const newOutline = cloneOutline(state.outline)
      const newNode: OutlineNode = {
        id: '',
        uid: nanoid(),
        name: '新章节',
        level: action.parentUid ? 2 : 1,
        required: false,
        has_template: false,
        children: []
      }

      if (action.parentUid === null) {
        // 添加一级节点
        newOutline.push(newNode)
      } else {
        // 添加为子节点
        const { node: parentNode } = findNode(newOutline, action.parentUid)
        if (parentNode && parentNode.level < 3) { // 最多3级
          newNode.level = parentNode.level + 1
          parentNode.children.push(newNode)
        }
      }

      const renumbered = renumberNodes(newOutline)
      return {
        ...state,
        outline: renumbered,
        history: [...state.history, renumbered],
        future: [],
        isDirty: true,
        saveStatus: 'idle',
        selectedUid: newNode.uid // 自动选中新节点
      }
    }

    case 'DELETE': {
      const newOutline = cloneOutline(state.outline)
      const { parent, index } = findNode(newOutline, action.uid)

      if (parent) {
        parent.children.splice(index, 1)
      } else {
        newOutline.splice(index, 1)
      }

      const renumbered = renumberNodes(newOutline)
      return {
        ...state,
        outline: renumbered,
        history: [...state.history, renumbered],
        future: [],
        isDirty: true,
        saveStatus: 'idle',
        selectedUid: state.selectedUid === action.uid ? null : state.selectedUid
      }
    }

    case 'MOVE': {
      if (!isMoveValid(state.outline, action.sourceUid, action.targetUid, action.position)) {
        return state
      }

      const newOutline = cloneOutline(state.outline)

      // 移除源节点
      const { node: sourceNode, parent: sourceParent, index: sourceIndex } = findNode(newOutline, action.sourceUid)
      if (!sourceNode) return state

      if (sourceParent) {
        sourceParent.children.splice(sourceIndex, 1)
      } else {
        newOutline.splice(sourceIndex, 1)
      }

      // 插入到目标位置
      const { node: targetNode, parent: targetParent, index: targetIndex } = findNode(newOutline, action.targetUid)
      if (!targetNode) return state

      if (action.position === 'inside') {
        // 变成子节点
        targetNode.children.push(sourceNode)
      } else if (action.position === 'before') {
        // 插入到前面
        if (targetParent) {
          targetParent.children.splice(targetIndex, 0, sourceNode)
        } else {
          newOutline.splice(targetIndex, 0, sourceNode)
        }
      } else if (action.position === 'after') {
        // 插入到后面
        if (targetParent) {
          targetParent.children.splice(targetIndex + 1, 0, sourceNode)
        } else {
          newOutline.splice(targetIndex + 1, 0, sourceNode)
        }
      }

      const renumbered = renumberNodes(newOutline)
      return {
        ...state,
        outline: renumbered,
        history: [...state.history, renumbered],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'TOGGLE_REQUIRED': {
      const newOutline = cloneOutline(state.outline)
      const { node } = findNode(newOutline, action.uid)
      if (node) {
        node.required = !node.required
      }
      return {
        ...state,
        outline: newOutline,
        history: [...state.history, newOutline],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'TOGGLE_TEMPLATE': {
      const newOutline = cloneOutline(state.outline)
      const { node } = findNode(newOutline, action.uid)
      if (node) {
        node.has_template = !node.has_template
      }
      return {
        ...state,
        outline: newOutline,
        history: [...state.history, newOutline],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'RENUMBER': {
      const renumbered = renumberNodes(state.outline)
      return {
        ...state,
        outline: renumbered,
        history: [...state.history, renumbered],
        future: [],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'UNDO': {
      if (state.history.length <= 1) return state // 没有可撤销的
      const previous = state.history[state.history.length - 2]
      const newHistory = state.history.slice(0, -1)
      return {
        ...state,
        outline: previous,
        history: newHistory,
        future: [state.outline, ...state.future],
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'REDO': {
      if (state.future.length === 0) return state // 没有可重做的
      const next = state.future[0]
      const newFuture = state.future.slice(1)
      return {
        ...state,
        outline: next,
        history: [...state.history, next],
        future: newFuture,
        isDirty: true,
        saveStatus: 'idle'
      }
    }

    case 'SAVE_START': {
      return {
        ...state,
        saveStatus: 'saving'
      }
    }

    case 'SAVE_SUCCESS': {
      return {
        ...state,
        isDirty: false,
        saveStatus: 'saved'
      }
    }

    case 'SAVE_FAILED': {
      return {
        ...state,
        saveStatus: 'failed'
      }
    }

    default:
      return state
  }
}

/**
 * 初始状态
 */
export function getInitialState(): EditorState {
  return {
    outline: [],
    selectedUid: null,
    history: [],
    future: [],
    isDirty: false,
    saveStatus: 'idle'
  }
}
