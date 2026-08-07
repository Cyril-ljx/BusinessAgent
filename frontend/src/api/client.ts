import axios from 'axios'

const APP_BASE_URL = import.meta.env.BASE_URL.replace(/\/+$/, '')
export const API_BASE_URL = `${APP_BASE_URL}/api`

export const apiUrl = (url: string) => {
  const value = String(url || '').trim()
  if (!value || /^(?:[a-z][a-z\d+.-]*:|\/\/|#)/i.test(value)) return value
  if (APP_BASE_URL && (value === APP_BASE_URL || value.startsWith(`${APP_BASE_URL}/`))) return value
  if (value === '/api' || value.startsWith('/api/')) return `${APP_BASE_URL}${value}`
  return value.startsWith('/') ? `${API_BASE_URL}${value}` : `${API_BASE_URL}/${value}`
}

// ============================================================
// 底层 axios 实例(直接 api.get / api.post 调用)
// 这个是命名导出,给现有页面用
// ============================================================
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  timeout: 30 * 60 * 1000, // 30 min,解析可能很慢
})

export const downloadFromUrl = (url: string) => {
  if (!url) return
  const resolvedUrl = apiUrl(url)
  const separator = resolvedUrl.includes('?') ? '&' : '?'
  const link = document.createElement('a')
  link.href = `${resolvedUrl}${separator}t=${Date.now()}`
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

// ============================================================
// 类型定义
// ============================================================
export interface OutlineNode {
  id: string
  name: string
  level: number
  required: boolean
  has_template: boolean
  children: OutlineNode[]
}

export interface TitleInfo {
  title: string
  project_name: string
  purchaser: string
}

export interface ParseResult {
  project_id: string
  title_info: TitleInfo
  outline: OutlineNode[]
  material_assignments?: unknown[]
  retrieval_summary?: {
    nodes?: unknown[]
    stats?: Record<string, number>
  }
  generated_sections?: Record<string, string>
  warnings: string[]
}

// ★ V11: 状态机精简对齐
export interface TaskStatus {
  project_id?: string
  status:
    | 'pending'
    | 'parsing'     // 步骤1：解析
    | 'locating'    // 步骤2：定位
    | 'composing'
    | 'outline_review'   // ★ V11新增：步骤3，一次性生成最终目录
    | 'done'        // 步骤4：完成
    | 'failed'
    | 'cancelled'   // ★ 补充任务取消状态
  progress: number   // 0-100
  message: string
  current_step?: string
  result?: ParseResult
  error?: string
  step_times?: Record<string, number>
}

export interface KnowledgeCategory {
  name: string
  count: number
}

export interface Company {
  id: string
  name: string
  is_default: boolean
  is_active: boolean
}

export interface CompanyCreatePayload {
  id?: string
  name: string
  is_default?: boolean
}

export interface CompanyUpdatePayload {
  name?: string
  is_default?: boolean
  is_active?: boolean
}

export interface KnowledgeSummary {
  certificates: number
  tech_sections: number
  categories: KnowledgeCategory[]
}

export interface KnowledgeCertificate {
  id: string
  category: string
  subcategory?: string | null
  name: string
  cert_number?: string | null
  issuer?: string | null
  file_path: string
  file_type?: string | null
  expire_date?: string | null
  updated_at?: string | null
}

export interface KnowledgeTechSection {
  id: string
  chapter_id?: string | null
  title: string
  full_path?: string | null
  level: number
  category?: string | null
  span: number
  char_count?: number | null
  image_count?: number | null
  vector_graphic_count?: number | null
  visual_count?: number | null
  table_count?: number | null
  content_preview?: string | null
  content?: string | null
  content_html?: string | null
  paragraphs?: string[]
  master_path?: string | null
  image_urls?: Array<{ index: number; url: string }>
  rendered_preview_url?: string | null
}

export interface ProjectListItem {
  id: string
  filename: string
  project_name: string
  purchaser: string
  company_id: string
  company_name: string
  status: string
  progress: number
  message: string
  error?: string | null
  created_at?: string | null
  updated_at?: string | null
  has_result: boolean
  has_docx: boolean
  outline_count: number
  generated_section_count: number
  compliance_issue_count: number
  consistency_conflict_count: number
}


// ============================================================
// 高层封装(如果别处还有人用就保留兼容)
// ============================================================
export const tenderAPI = {
  uploadTender: async (
    file: File,
    companyId: string,
    companyName: string,
  ): Promise<{ project_id: string }> => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('company_id', companyId)
    fd.append('company_name', companyName)
    const r = await api.post('/projects/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return r.data
  },

  listCompanies: async (includeInactive = false): Promise<Company[]> => {
    const r = await api.get('/companies', { params: { include_inactive: includeInactive } })
    return r.data
  },

  createCompany: async (payload: CompanyCreatePayload): Promise<Company> => {
    const r = await api.post('/companies', payload)
    return r.data
  },

  updateCompany: async (companyId: string, payload: CompanyUpdatePayload): Promise<Company> => {
    const r = await api.put(`/companies/${companyId}`, payload)
    return r.data
  },

  deactivateCompany: async (companyId: string): Promise<{ ok: boolean }> => {
    const r = await api.delete(`/companies/${companyId}`)
    return r.data
  },

  getTaskStatus: async (projectId: string): Promise<TaskStatus> => {
    const r = await api.get(`/projects/${projectId}/status`)
    return r.data
  },

  getOutline: async (projectId: string): Promise<ParseResult> => {
    const r = await api.get(`/projects/${projectId}/outline`)
    return r.data
  },

  renderBlankBid: async (projectId: string): Promise<{ download_url: string }> => {
    const r = await api.post(`/projects/${projectId}/render`)
    return r.data
  },

  getKnowledgeSummary: async (companyId?: string): Promise<KnowledgeSummary> => {
    const r = await api.get('/knowledge/summary', { params: { company_id: companyId } })
    return r.data
  },

  listCertificates: async (params?: {
    q?: string
    category?: string
    limit?: number
    company_id?: string
  }): Promise<KnowledgeCertificate[]> => {
    const r = await api.get('/knowledge/certificates', { params })
    return r.data
  },

  listTechSections: async (params?: {
    q?: string
    limit?: number
    company_id?: string
  }): Promise<KnowledgeTechSection[]> => {
    const r = await api.get('/knowledge/tech-sections', { params })
    return r.data
  },

  previewTechSection: async (
    id: string,
    params?: { company_id?: string },
  ): Promise<KnowledgeTechSection> => {
    const r = await api.get(`/knowledge/tech-sections/${id}/preview`, { params })
    return r.data
  },

  listProjects: async (params?: { limit?: number }): Promise<ProjectListItem[]> => {
    const r = await api.get('/projects', { params })
    return r.data
  },

  deleteProject: async (projectId: string): Promise<{ ok: boolean; deleted_files: number }> => {
    const r = await api.delete(`/projects/${projectId}`)
    return r.data
  },

  uploadCertificate: async (formData: FormData): Promise<{ ok: boolean; id: string; file_path: string }> => {
    const r = await api.post('/knowledge/certificates/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return r.data
  },

  importCertificateDocx: async (formData: FormData): Promise<{
    ok: boolean
    image_count: number
    heading_count: number
    imported_count: number
    file_path: string
    categories: KnowledgeCategory[]
  }> => {
    const r = await api.post('/knowledge/certificates/import-docx', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return r.data
  },

  updateCertificate: async (id: string, body: Partial<KnowledgeCertificate>): Promise<{ ok: boolean }> => {
    const r = await api.put(`/knowledge/certificates/${id}`, body)
    return r.data
  },

  deleteCertificate: async (id: string): Promise<{ ok: boolean }> => {
    const r = await api.delete(`/knowledge/certificates/${id}`)
    return r.data
  },

  uploadTechMaster: async (formData: FormData): Promise<{ ok: boolean; section_count: number; file_path: string }> => {
    const r = await api.post('/knowledge/tech-master/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return r.data
  },

  updateTechSection: async (id: string, body: Partial<KnowledgeTechSection> & { keywords?: string | string[] }): Promise<{ ok: boolean }> => {
    const r = await api.put(`/knowledge/tech-sections/${id}`, body)
    return r.data
  },

  deleteTechSection: async (id: string): Promise<{ ok: boolean; deleted_count: number }> => {
    const r = await api.delete(`/knowledge/tech-sections/${id}`)
    return r.data
  },

  deleteTechSections: async (sectionIds: string[]): Promise<{ ok: boolean; deleted_count: number }> => {
    const r = await api.post('/knowledge/tech-sections/bulk-delete', { section_ids: sectionIds })
    return r.data
  },
}
