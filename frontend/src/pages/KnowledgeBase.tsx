import React, { useEffect, useRef, useState } from 'react'
import { CircleAlert, CircleCheck, Database, Eye, FileBadge, Layers3, LoaderCircle, Pencil, Save, Search, Trash2, UploadCloud, X } from 'lucide-react'
import { apiUrl, tenderAPI, type Company, type KnowledgeCertificate, type KnowledgeSummary, type KnowledgeTechSection } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const emptySummary: KnowledgeSummary = {
  certificates: 0,
  tech_sections: 0,
  categories: [],
}

type KnowledgePreviewTarget =
  | { kind: 'certificate'; item: KnowledgeCertificate }
  | { kind: 'tech'; item: KnowledgeTechSection }

const normalizePreviewHtml = (value: string) => value.replace(
  /(src|href)=(['"])([^'"]+)\2/gi,
  (_match, attribute: string, quote: string, url: string) => `${attribute}=${quote}${apiUrl(url)}${quote}`,
)

const apiErrorMessage = (error: any, fallback: string) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => String(item?.msg || item?.message || '').trim())
      .filter(Boolean)
    if (messages.length) return messages.join('；')
  }
  const responseText = error?.response?.data
  if (typeof responseText === 'string' && responseText.trim() && responseText !== 'Internal Server Error') {
    return responseText
  }
  return fallback
}

const KnowledgeBase: React.FC = () => {
  const [summary, setSummary] = useState<KnowledgeSummary>(emptySummary)
  const [companies, setCompanies] = useState<Company[]>([])
  const [companyId, setCompanyId] = useState('demo-company')
  const [materialScope, setMaterialScope] = useState<'company' | 'shared'>('company')
  const [certificates, setCertificates] = useState<KnowledgeCertificate[]>([])
  const [techSections, setTechSections] = useState<KnowledgeTechSection[]>([])
  const [query, setQuery] = useState('')
  const [activeTab, setActiveTab] = useState<'certificates' | 'tech'>('certificates')
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingCertId, setEditingCertId] = useState('')
  const [editingTechId, setEditingTechId] = useState('')
  const [selectedTechIds, setSelectedTechIds] = useState<Set<string>>(new Set())
  const [certEdit, setCertEdit] = useState<Record<string, any>>({})
  const [techEdit, setTechEdit] = useState<Record<string, any>>({})
  const [previewTarget, setPreviewTarget] = useState<KnowledgePreviewTarget | null>(null)
  const [techPreview, setTechPreview] = useState<KnowledgeTechSection | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const previewRequestRef = useRef(0)

  const [certFile, setCertFile] = useState<File | null>(null)
  const [certBundleFile, setCertBundleFile] = useState<File | null>(null)
  const [certCategory, setCertCategory] = useState('营业执照')
  const [certName, setCertName] = useState('')
  const [certSubcategory, setCertSubcategory] = useState('')
  const [certExpireDate, setCertExpireDate] = useState('')
  const [techMasterFile, setTechMasterFile] = useState<File | null>(null)

  const loadData = async (nextQuery = query, nextCompanyId = companyId) => {
    setLoading(true)
    setError('')
    try {
      const [summaryData, certRows, techRows] = await Promise.all([
        tenderAPI.getKnowledgeSummary(nextCompanyId),
        tenderAPI.listCertificates({ q: nextQuery || undefined, limit: 500, company_id: nextCompanyId }),
        tenderAPI.listTechSections({ q: nextQuery || undefined, limit: 220, company_id: nextCompanyId }),
      ])
      setSummary(summaryData)
      setCertificates(certRows)
      setTechSections(techRows)
      const visibleIds = new Set(techRows.map((item) => item.id))
      setSelectedTechIds((current) => new Set([...current].filter((id) => visibleIds.has(id))))
    } catch (err: any) {
      setError(apiErrorMessage(err, '知识库读取失败，请检查后端服务和数据库连接'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const bootstrap = async () => {
      try {
        const rows = await tenderAPI.listCompanies()
        setCompanies(rows)
        const selected = rows.find((item) => item.is_default) || rows[0]
        if (selected) {
          setCompanyId(selected.id)
          await loadData('', selected.id)
          return
        }
      } catch (err) {
        setCompanies([
          {
            id: 'demo-company',
            name: '示例科技服务有限公司',
            is_default: true,
            is_active: true,
          },
        ])
      }
      await loadData('', 'demo-company')
    }
    bootstrap()
  }, [])

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault()
    loadData(query.trim())
  }

  const handleUploadCertificate = async () => {
    if (!certFile || !certCategory.trim() || !certName.trim()) {
      setError('请填写分类、名称并选择证书文件')
      return
    }
    setUploading(true)
    setError('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('file', certFile)
      fd.append('company_id', companyId)
      fd.append('scope', materialScope)
      fd.append('category', certCategory)
      fd.append('name', certName)
      fd.append('subcategory', certSubcategory)
      fd.append('expire_date', certExpireDate)
      await tenderAPI.uploadCertificate(fd)
      setNotice('证书素材已入库')
      setCertFile(null)
      setCertName('')
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '证书上传失败'))
    } finally {
      setUploading(false)
    }
  }

  const handleImportCertificateDocx = async () => {
    if (!certBundleFile) {
      setError('请选择证书合集 DOCX')
      return
    }
    setUploading(true)
    setError('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('file', certBundleFile)
      fd.append('company_id', companyId)
      fd.append('scope', materialScope)
      const res = await tenderAPI.importCertificateDocx(fd)
      const summary = (res.categories || []).slice(0, 4).map((item) => `${item.name} ${item.count}`).join('，')
      setNotice(`证书合集已导入 ${res.imported_count} 张图片证书${summary ? `（${summary}）` : ''}`)
      setCertBundleFile(null)
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '证书合集导入失败'))
    } finally {
      setUploading(false)
    }
  }

  const handleUploadTechMaster = async () => {
    if (!techMasterFile) {
      setError('请选择技术母版 DOCX')
      return
    }
    setUploading(true)
    setError('')
    setNotice('')
    try {
      const fd = new FormData()
      fd.append('file', techMasterFile)
      fd.append('company_id', companyId)
      fd.append('scope', materialScope)
      const res = await tenderAPI.uploadTechMaster(fd)
      setNotice(`技术母版已扫描，入库章节 ${res.section_count} 个`)
      setTechMasterFile(null)
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '技术母版上传失败'))
    } finally {
      setUploading(false)
    }
  }

  const beginEditCert = (item: KnowledgeCertificate) => {
    setEditingCertId(item.id)
    setCertEdit({
      category: item.category || '',
      subcategory: item.subcategory || '',
      name: item.name || '',
      expire_date: item.expire_date || '',
    })
  }

  const saveCertEdit = async (id: string) => {
    setUploading(true)
    setError('')
    try {
      await tenderAPI.updateCertificate(id, certEdit)
      setNotice('证书素材已更新')
      setEditingCertId('')
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '证书更新失败'))
    } finally {
      setUploading(false)
    }
  }

  const deleteCert = async (id: string) => {
    if (!window.confirm('确定删除这条证书素材吗？')) return
    setUploading(true)
    setError('')
    try {
      await tenderAPI.deleteCertificate(id)
      setNotice('证书素材已删除')
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '证书删除失败，请查看服务器日志'))
    } finally {
      setUploading(false)
    }
  }

  const beginEditTech = (item: KnowledgeTechSection) => {
    setEditingTechId(item.id)
    setTechEdit({
      chapter_id: item.chapter_id || '',
      title: item.title || '',
      full_path: item.full_path || '',
      category: item.category || '',
    })
  }

  const saveTechEdit = async (id: string) => {
    setUploading(true)
    setError('')
    try {
      await tenderAPI.updateTechSection(id, techEdit)
      setNotice('技术章节已更新')
      setEditingTechId('')
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '技术章节更新失败'))
    } finally {
      setUploading(false)
    }
  }

  const deleteTech = async (item: KnowledgeTechSection) => {
    if (!window.confirm(`确定删除“${item.title}”吗？如有下级章节将一并删除。`)) return
    setUploading(true)
    setError('')
    try {
      const result = await tenderAPI.deleteTechSection(item.id)
      setNotice(`技术章节已删除，共 ${result.deleted_count || 1} 条`)
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '技术章节删除失败'))
    } finally {
      setUploading(false)
    }
  }

  const openCertificatePreview = (item: KnowledgeCertificate) => {
    previewRequestRef.current += 1
    setPreviewLoading(false)
    setPreviewError('')
    setTechPreview(null)
    setPreviewTarget({ kind: 'certificate', item })
  }

  const openTechPreview = async (item: KnowledgeTechSection) => {
    const requestId = ++previewRequestRef.current
    setPreviewTarget({ kind: 'tech', item })
    setTechPreview(null)
    setPreviewError('')
    setPreviewLoading(true)
    try {
      const preview = await tenderAPI.previewTechSection(item.id, { company_id: companyId })
      if (requestId === previewRequestRef.current) setTechPreview(preview)
    } catch (err: any) {
      if (requestId === previewRequestRef.current) {
        setPreviewError(err?.response?.data?.detail || err?.message || '技术章节预览加载失败')
      }
    } finally {
      if (requestId === previewRequestRef.current) setPreviewLoading(false)
    }
  }

  const allTechSelected = techSections.length > 0 && techSections.every((item) => selectedTechIds.has(item.id))

  const toggleTechSelection = (id: string) => {
    setSelectedTechIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAllTechSections = () => {
    setSelectedTechIds(allTechSelected ? new Set() : new Set(techSections.map((item) => item.id)))
  }

  const deleteSelectedTechSections = async () => {
    const sectionIds = [...selectedTechIds]
    if (!sectionIds.length) return
    if (!window.confirm(`确定删除选中的 ${sectionIds.length} 个技术章节吗？如包含父章节，其下级章节也会一并删除。`)) return
    setUploading(true)
    setError('')
    try {
      const result = await tenderAPI.deleteTechSections(sectionIds)
      setSelectedTechIds(new Set())
      setNotice(`批量删除完成，共删除 ${result.deleted_count} 条技术章节`)
      await loadData(query)
    } catch (err: any) {
      setError(apiErrorMessage(err, '技术章节批量删除失败'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-emerald-950 p-6 text-white shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-emerald-100 ring-1 ring-white/15">
              <Database className="h-3.5 w-3.5" />
              本地知识库管理
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">素材库 / 技术母版</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300">
              支持录入证书素材、批量导入证书合集和扫描技术母版。
            </p>
            <div className="mt-4 grid max-w-2xl gap-3 md:grid-cols-2">
              <div>
                <Label htmlFor="knowledge-company" className="mb-2 block text-xs text-emerald-100">
                  当前知识库公司
                </Label>
                <select
                  id="knowledge-company"
                  value={companyId}
                  onChange={(event) => {
                    const nextId = event.target.value
                    setCompanyId(nextId)
                    loadData('', nextId)
                  }}
                  className="h-10 w-full rounded-lg border border-white/15 bg-white/10 px-3 text-sm text-white outline-none"
                >
                  {companies.length === 0 ? (
                    <option className="text-slate-900" value="demo-company">示例科技服务有限公司</option>
                  ) : (
                    companies.map((item) => (
                      <option className="text-slate-900" key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))
                  )}
                </select>
              </div>
              <div>
                <Label htmlFor="material-scope" className="mb-2 block text-xs text-emerald-100">
                  新上传素材归属
                </Label>
                <select
                  id="material-scope"
                  value={materialScope}
                  onChange={(event) => setMaterialScope(event.target.value as 'company' | 'shared')}
                  className="h-10 w-full rounded-lg border border-white/15 bg-white/10 px-3 text-sm text-white outline-none"
                >
                  <option className="text-slate-900" value="company">当前公司专属</option>
                  <option className="text-slate-900" value="shared">全公司共享</option>
                </select>
              </div>
            </div>
          </div>
          <form onSubmit={handleSearch} className="flex w-full gap-2 lg:w-[420px]">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索：营业执照 / 招聘 / 项目管理"
                className="h-10 border-white/15 bg-white/10 pl-9 text-white placeholder:text-slate-400"
              />
            </div>
            <Button type="submit" disabled={loading} className="h-10 bg-emerald-400 text-slate-950 hover:bg-emerald-300">
              {loading ? '查询中' : '查询'}
            </Button>
          </form>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="border-slate-200 bg-white">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><FileBadge className="h-4 w-4 text-emerald-600" />证书素材</CardTitle>
            <CardDescription>证照、业绩、审计报告等证明材料</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold text-slate-900">{summary.certificates}</div></CardContent>
        </Card>
        <Card className="border-slate-200 bg-white">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-blue-600" />技术章节</CardTitle>
            <CardDescription>从技术母版和历史文档抽取</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold text-slate-900">{summary.tech_sections}</div></CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader className="space-y-2 pb-4"><CardTitle>录入证书素材</CardTitle><CardDescription>单张图片/PDF 入 certificates 表</CardDescription></CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2"><Label>素材文件</Label><Input className="h-11" type="file" accept=".png,.jpg,.jpeg,.webp,.pdf" onChange={(e) => setCertFile(e.target.files?.[0] || null)} /></div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label>分类</Label><Input className="h-11" value={certCategory} onChange={(e) => setCertCategory(e.target.value)} /></div>
              <div className="space-y-2"><Label>名称</Label><Input className="h-11" value={certName} onChange={(e) => setCertName(e.target.value)} placeholder="如：营业执照" /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label>子分类</Label><Input className="h-11" value={certSubcategory} onChange={(e) => setCertSubcategory(e.target.value)} /></div>
              <div className="space-y-2"><Label>有效期</Label><Input className="h-11" type="date" value={certExpireDate} onChange={(e) => setCertExpireDate(e.target.value)} /></div>
            </div>
            <Button className="h-11 px-5" onClick={handleUploadCertificate} disabled={uploading}><UploadCloud className="h-4 w-4" />入库证书</Button>
            <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4">
              <div className="text-sm font-medium text-slate-900">批量导入证书合集 DOCX</div>
              <div className="mt-1 text-xs leading-5 text-slate-500">
                按 Word/WPS 标题层级拆分：H1 作为大类，最近标题作为证书名称，标题下图片会分别写入 certificates。
              </div>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                <Input className="h-11" type="file" accept=".docx" onChange={(e) => setCertBundleFile(e.target.files?.[0] || null)} />
                <Button className="h-11 whitespace-nowrap" variant="outline" onClick={handleImportCertificateDocx} disabled={uploading}>
                  <UploadCloud className="h-4 w-4" />导入合集
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader className="space-y-2 pb-4"><CardTitle>扫描技术母版</CardTitle><CardDescription>上传 DOCX 后重建技术章节索引</CardDescription></CardHeader>
          <CardContent className="space-y-5">
            <Input className="h-11" type="file" accept=".docx" onChange={(e) => setTechMasterFile(e.target.files?.[0] || null)} />
            <div className="text-xs text-slate-500">会覆盖当前归属下的 technical_master 分类索引；公司专属会保存到该公司目录，共享会保存到 shared 目录。</div>
            <Button className="h-11 px-5" onClick={handleUploadTechMaster} disabled={uploading}><Layers3 className="h-4 w-4" />上传并扫描</Button>
          </CardContent>
        </Card>

      </div>

      <Card className="border-slate-200 bg-white">
        <CardHeader><CardTitle>素材分类</CardTitle><CardDescription>按证书大类统计，快速判断材料库是否缺项</CardDescription></CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {summary.categories.map((item) => (
              <button key={item.name} type="button" onClick={() => { setActiveTab('certificates'); setQuery(item.name); loadData(item.name, companyId) }} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 transition hover:border-emerald-300 hover:bg-emerald-50">
                {item.name} <span className="text-slate-400">{item.count}</span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button variant={activeTab === 'certificates' ? 'default' : 'outline'} onClick={() => setActiveTab('certificates')}>证书素材 ({certificates.length}/{summary.certificates})</Button>
        <Button variant={activeTab === 'tech' ? 'default' : 'outline'} onClick={() => setActiveTab('tech')}>技术章节 ({techSections.length})</Button>
      </div>

      {activeTab === 'certificates' ? (
        <Card className="border-slate-200 bg-white"><CardContent className="p-0"><div className="divide-y divide-slate-100">
          {certificates.map((item) => (
            <div key={item.id} className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[180px_1fr_220px_250px]">
              {editingCertId === item.id ? (
                <>
                  <div className="space-y-2">
                    <Label className="text-xs">分类</Label>
                    <Input value={certEdit.category || ''} onChange={(event) => setCertEdit({ ...certEdit, category: event.target.value })} />
                    <Label className="text-xs">子分类</Label>
                    <Input value={certEdit.subcategory || ''} onChange={(event) => setCertEdit({ ...certEdit, subcategory: event.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs">名称</Label>
                    <Input value={certEdit.name || ''} onChange={(event) => setCertEdit({ ...certEdit, name: event.target.value })} />
                    <div className="break-all text-xs text-slate-500">{item.file_path}</div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs">有效期</Label>
                    <Input type="date" value={certEdit.expire_date || ''} onChange={(event) => setCertEdit({ ...certEdit, expire_date: event.target.value })} />
                  </div>
                  <div className="flex items-start justify-end gap-2">
                    <Button size="sm" onClick={() => saveCertEdit(item.id)} disabled={uploading}><Save className="h-3.5 w-3.5" />保存</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingCertId('')} disabled={uploading}><X className="h-3.5 w-3.5" />取消</Button>
                  </div>
                </>
              ) : (
                <>
                  <div><Badge variant="secondary">{item.category}</Badge>{item.subcategory && <div className="mt-1 text-xs text-slate-500">{item.subcategory}</div>}</div>
                  <div><div className="font-medium text-slate-900">{item.name}</div><div className="mt-1 break-all text-xs text-slate-500">{item.file_path}</div></div>
                  <div className="text-xs text-slate-500">
                    {item.expire_date ? <div>有效期：{item.expire_date}</div> : <div>未维护有效期字段</div>}
                  </div>
                  <div className="flex items-start justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => openCertificatePreview(item)} disabled={uploading}><Eye className="h-3.5 w-3.5" />预览</Button>
                    <Button size="sm" variant="outline" onClick={() => beginEditCert(item)} disabled={uploading}><Pencil className="h-3.5 w-3.5" />编辑</Button>
                    <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700" onClick={() => deleteCert(item.id)} disabled={uploading}><Trash2 className="h-3.5 w-3.5" />删除</Button>
                  </div>
                </>
              )}
            </div>
          ))}
          {!loading && certificates.length === 0 && <div className="px-4 py-10 text-center text-sm text-slate-500">没有匹配到证书素材</div>}
        </div></CardContent></Card>
      ) : (
        <Card className="border-slate-200 bg-white"><CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 accent-blue-600"
                checked={allTechSelected}
                onChange={toggleAllTechSections}
                disabled={uploading || techSections.length === 0}
              />
              全选当前列表
            </label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">已选 {selectedTechIds.size} 项</span>
              <Button
                size="sm"
                variant="outline"
                className="text-red-600 hover:text-red-700"
                onClick={deleteSelectedTechSections}
                disabled={uploading || selectedTechIds.size === 0}
              >
                <Trash2 className="h-3.5 w-3.5" />批量删除
              </Button>
            </div>
          </div>
          <div className="divide-y divide-slate-100">
          {techSections.map((item) => (
            <div key={item.id} className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[36px_120px_1fr_220px_250px]">
              <div className="flex items-start pt-1">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 accent-blue-600"
                  checked={selectedTechIds.has(item.id)}
                  onChange={() => toggleTechSelection(item.id)}
                  disabled={uploading || editingTechId === item.id}
                  aria-label={`选择 ${item.title}`}
                />
              </div>
              {editingTechId === item.id ? (
                <>
                  <div className="space-y-2">
                    <Label className="text-xs">章节号</Label>
                    <Input value={techEdit.chapter_id || ''} onChange={(event) => setTechEdit({ ...techEdit, chapter_id: event.target.value })} />
                    <Label className="text-xs">分类</Label>
                    <Input value={techEdit.category || ''} onChange={(event) => setTechEdit({ ...techEdit, category: event.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs">标题</Label>
                    <Input value={techEdit.title || ''} onChange={(event) => setTechEdit({ ...techEdit, title: event.target.value })} />
                    <Label className="text-xs">完整路径</Label>
                    <Input value={techEdit.full_path || ''} onChange={(event) => setTechEdit({ ...techEdit, full_path: event.target.value })} />
                  </div>
                  <div className="flex flex-wrap content-start gap-2 text-xs text-slate-500">
                    <Badge variant="outline">L{item.level}</Badge>
                    <Badge variant={item.span > 180 ? 'destructive' : 'secondary'}>跨度 {item.span}</Badge>
                    <span>图/图形 {item.visual_count ?? item.image_count ?? 0}</span>
                    <span>表 {item.table_count ?? 0}</span>
                  </div>
                  <div className="flex items-start justify-end gap-2">
                    <Button size="sm" onClick={() => saveTechEdit(item.id)} disabled={uploading}><Save className="h-3.5 w-3.5" />保存</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingTechId('')} disabled={uploading}><X className="h-3.5 w-3.5" />取消</Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="font-mono text-slate-500">{item.chapter_id}</div>
                  <div><div className="font-medium text-slate-900">{item.title}</div><div className="mt-1 text-xs text-slate-500">{item.full_path || '无路径'}</div></div>
                  <div className="flex flex-wrap gap-2 text-xs text-slate-500"><Badge variant="outline">L{item.level}</Badge><Badge variant={item.span > 180 ? 'destructive' : 'secondary'}>跨度 {item.span}</Badge><span>图/图形 {item.visual_count ?? item.image_count ?? 0}</span><span>表 {item.table_count ?? 0}</span></div>
                  <div className="flex items-start justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => void openTechPreview(item)} disabled={uploading}><Eye className="h-3.5 w-3.5" />预览</Button>
                    <Button size="sm" variant="outline" onClick={() => beginEditTech(item)} disabled={uploading}><Pencil className="h-3.5 w-3.5" />编辑</Button>
                    <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700" onClick={() => deleteTech(item)} disabled={uploading}><Trash2 className="h-3.5 w-3.5" />删除</Button>
                  </div>
                </>
              )}
            </div>
          ))}
          {!loading && techSections.length === 0 && <div className="px-4 py-10 text-center text-sm text-slate-500">没有匹配到技术章节</div>}
          </div>
        </CardContent></Card>
      )}

      <Dialog
        open={Boolean(previewTarget)}
        onOpenChange={(open) => {
          if (!open) {
            previewRequestRef.current += 1
            setPreviewTarget(null)
            setTechPreview(null)
            setPreviewError('')
            setPreviewLoading(false)
          }
        }}
      >
        <DialogContent className="flex h-[96vh] max-h-[96vh] w-[96vw] max-w-[96vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[96vw]">
          <DialogHeader className="shrink-0 border-b px-6 py-4 pr-14">
            <DialogTitle>
              {previewTarget?.kind === 'certificate'
                ? previewTarget.item.name
                : previewTarget?.kind === 'tech'
                  ? previewTarget.item.title
                  : '素材预览'}
            </DialogTitle>
            <DialogDescription>
              {previewTarget?.kind === 'certificate'
                ? `${previewTarget.item.category}${previewTarget.item.subcategory ? ` / ${previewTarget.item.subcategory}` : ''}`
                : previewTarget?.item.full_path || '技术文件章节内容'}
            </DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-slate-100 p-3">
            {previewError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{previewError}</div>
            ) : previewTarget?.kind === 'certificate' ? (
              <div className="grid min-h-[560px] gap-4 lg:grid-cols-[260px_1fr]">
                <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm">
                  <div className="text-xs font-medium uppercase tracking-wider text-slate-400">素材信息</div>
                  <div className="mt-4 space-y-3 text-slate-600">
                    <div><span className="text-slate-400">分类：</span>{previewTarget.item.category}</div>
                    <div><span className="text-slate-400">名称：</span>{previewTarget.item.name}</div>
                    {previewTarget.item.cert_number && <div><span className="text-slate-400">编号：</span>{previewTarget.item.cert_number}</div>}
                    {previewTarget.item.issuer && <div><span className="text-slate-400">颁发机构：</span>{previewTarget.item.issuer}</div>}
                    {previewTarget.item.expire_date && <div><span className="text-slate-400">有效期：</span>{previewTarget.item.expire_date}</div>}
                    <div className="break-all text-xs text-slate-400">{previewTarget.item.file_path}</div>
                  </div>
                </div>
                <div className="flex min-h-[560px] items-center justify-center overflow-hidden rounded-2xl border border-slate-200 bg-white p-3">
                  {(previewTarget.item.file_type || previewTarget.item.file_path).toLowerCase().includes('pdf') ? (
                    <iframe
                      title={previewTarget.item.name}
                      src={apiUrl(`/knowledge/certificates/${previewTarget.item.id}/file`)}
                      className="h-[70vh] min-h-[540px] w-full rounded-lg border-0"
                    />
                  ) : (
                    <img
                      src={apiUrl(`/knowledge/certificates/${previewTarget.item.id}/file`)}
                      alt={previewTarget.item.name}
                      className="max-h-[70vh] max-w-full object-contain"
                    />
                  )}
                </div>
              </div>
            ) : previewLoading ? (
              <div className="flex min-h-[560px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-sm text-slate-500">
                <LoaderCircle className="mr-2 h-5 w-5 animate-spin" />正在加载技术文件内容...
              </div>
            ) : techPreview ? (
              <div className="h-full w-full rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="mb-3 flex flex-wrap gap-2 border-b border-slate-100 pb-3 text-xs text-slate-500">
                  <Badge variant="outline">章节 {techPreview.chapter_id || '-'}</Badge>
                  <Badge variant="outline">图/图形 {techPreview.visual_count ?? techPreview.image_count ?? 0}</Badge>
                  <Badge variant="outline">表 {techPreview.table_count ?? 0}</Badge>
                  <Badge variant="outline">字数 {techPreview.char_count ?? 0}</Badge>
                </div>
                {techPreview.rendered_preview_url ? (
                  <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                    <div className="border-b border-slate-200 bg-white px-4 py-2 text-xs text-slate-500">
                      该章节包含 Word 流程图或文本框，以下按原文件版式展示。
                    </div>
                    <iframe
                      title={`${techPreview.title}-原版预览`}
                      src={`${apiUrl(techPreview.rendered_preview_url)}#page=1&zoom=page-width&navpanes=0`}
                      className="h-[78vh] min-h-[640px] w-full border-0 bg-white"
                    />
                  </div>
                ) : techPreview.content_html ? (
                  <div
                    className="prose prose-slate max-w-none text-sm leading-7 [&_img]:mx-auto [&_img]:my-4 [&_img]:max-h-[520px] [&_img]:max-w-full [&_table]:my-4 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-300 [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-slate-300 [&_th]:px-3 [&_th]:py-2"
                    dangerouslySetInnerHTML={{ __html: normalizePreviewHtml(techPreview.content_html) }}
                  />
                ) : (
                  <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{techPreview.content || techPreview.content_preview || '该章节没有可展示的正文。'}</div>
                )}
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(error || notice)}
        onOpenChange={(open) => {
          if (!open) {
            setError('')
            setNotice('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <div className={`mb-2 flex h-11 w-11 items-center justify-center rounded-full ${error ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'}`}>
              {error ? <CircleAlert className="h-6 w-6" /> : <CircleCheck className="h-6 w-6" />}
            </div>
            <DialogTitle>{error ? '操作失败' : '操作成功'}</DialogTitle>
            <DialogDescription className="break-words text-sm leading-6 text-slate-600">
              {error || notice}
            </DialogDescription>
          </DialogHeader>
          <Button
            className="mt-2 w-full"
            variant={error ? 'outline' : 'default'}
            onClick={() => {
              setError('')
              setNotice('')
            }}
          >
            知道了
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default KnowledgeBase
