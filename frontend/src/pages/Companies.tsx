import React, { useEffect, useState } from 'react'
import { Building2, CheckCircle2, Plus, RefreshCw, Save, Shield, Trash2 } from 'lucide-react'
import { tenderAPI, type Company } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const DEFAULT_COMPANY_ID = 'demo-company'

const Companies: React.FC = () => {
  const [companies, setCompanies] = useState<Company[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [newName, setNewName] = useState('')
  const [newId, setNewId] = useState('')
  const [makeDefault, setMakeDefault] = useState(false)
  const [editingId, setEditingId] = useState('')
  const [editingName, setEditingName] = useState('')

  const activeCompanies = companies.filter((item) => item.is_active)
  const inactiveCompanies = companies.filter((item) => !item.is_active)
  const defaultCompany = companies.find((item) => item.is_default)

  const loadCompanies = async () => {
    setLoading(true)
    setError('')
    try {
      const rows = await tenderAPI.listCompanies(true)
      setCompanies(rows)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '公司列表读取失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCompanies()
  }, [])

  const createCompany = async () => {
    if (!newName.trim()) {
      setError('请填写公司名称')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await tenderAPI.createCompany({
        name: newName.trim(),
        id: newId.trim() || undefined,
        is_default: makeDefault,
      })
      setNotice('公司已创建，可以在新建项目和知识库中选择')
      setNewName('')
      setNewId('')
      setMakeDefault(false)
      await loadCompanies()
    } catch (err: any) {
      setError(err?.response?.data?.detail || '公司创建失败')
    } finally {
      setSaving(false)
    }
  }

  const saveName = async (company: Company) => {
    if (!editingName.trim()) {
      setError('公司名称不能为空')
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await tenderAPI.updateCompany(company.id, { name: editingName.trim() })
      setNotice('公司名称已更新')
      setEditingId('')
      setEditingName('')
      await loadCompanies()
    } catch (err: any) {
      setError(err?.response?.data?.detail || '公司更新失败')
    } finally {
      setSaving(false)
    }
  }

  const setDefault = async (company: Company) => {
    if (company.is_default) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await tenderAPI.updateCompany(company.id, { is_default: true })
      setNotice(`${company.name} 已设为默认公司`)
      await loadCompanies()
    } catch (err: any) {
      setError(err?.response?.data?.detail || '默认公司设置失败')
    } finally {
      setSaving(false)
    }
  }

  const deactivate = async (company: Company) => {
    if (!window.confirm(`确定停用「${company.name}」吗？历史项目不会删除，但新建项目不再显示。`)) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await tenderAPI.deactivateCompany(company.id)
      setNotice('公司已停用')
      await loadCompanies()
    } catch (err: any) {
      setError(err?.response?.data?.detail || '公司停用失败')
    } finally {
      setSaving(false)
    }
  }

  const reactivate = async (company: Company) => {
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await tenderAPI.updateCompany(company.id, { is_active: true })
      setNotice('公司已重新启用')
      await loadCompanies()
    } catch (err: any) {
      setError(err?.response?.data?.detail || '公司启用失败')
    } finally {
      setSaving(false)
    }
  }

  const renderCompanyRow = (company: Company) => {
    const isEditing = editingId === company.id
    return (
      <div key={company.id} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-[1fr_220px_260px] md:items-center">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            {isEditing ? (
              <Input value={editingName} onChange={(event) => setEditingName(event.target.value)} className="h-10 max-w-lg" />
            ) : (
              <div className="text-base font-semibold text-slate-900">{company.name}</div>
            )}
            {company.is_default && <Badge className="bg-emerald-600">默认</Badge>}
            {!company.is_active && <Badge variant="outline">已停用</Badge>}
          </div>
          <div className="mt-1 text-xs text-slate-500">company_id: {company.id}</div>
          <div className="mt-2 text-xs text-slate-500">
            专属素材只会在选择该公司时使用；共享素材仍可被所有公司复用。
          </div>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <div className="font-medium text-slate-800">知识库隔离</div>
          <div className="mt-1">company + shared</div>
        </div>
        <div className="flex flex-wrap justify-start gap-2 md:justify-end">
          {isEditing ? (
            <>
              <Button size="sm" onClick={() => saveName(company)} disabled={saving}><Save className="h-3.5 w-3.5" />保存</Button>
              <Button size="sm" variant="outline" onClick={() => { setEditingId(''); setEditingName('') }} disabled={saving}>取消</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={() => { setEditingId(company.id); setEditingName(company.name) }} disabled={saving}>改名</Button>
              <Button size="sm" variant="outline" onClick={() => setDefault(company)} disabled={saving || company.is_default || !company.is_active}>
                <CheckCircle2 className="h-3.5 w-3.5" />设默认
              </Button>
              {company.is_active ? (
                <Button size="sm" variant="outline" className="text-red-600 hover:text-red-700" onClick={() => deactivate(company)} disabled={saving || company.id === DEFAULT_COMPANY_ID || company.is_default}>
                  <Trash2 className="h-3.5 w-3.5" />停用
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => reactivate(company)} disabled={saving}>启用</Button>
              )}
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950 p-6 text-white shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-cyan-100 ring-1 ring-white/15">
              <Building2 className="h-3.5 w-3.5" />
              多公司知识库隔离
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">公司管理</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300">
              每家公司拥有独立的证书、技术母版、历史投标素材；共享素材仍可跨公司复用，避免湖北项目贴到广东材料。
            </p>
          </div>
          <Button onClick={loadCompanies} disabled={loading} className="bg-cyan-300 text-slate-950 hover:bg-cyan-200">
            <RefreshCw className="h-4 w-4" />刷新
          </Button>
        </div>
      </div>

      {notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{notice}</div>}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4 text-cyan-600" />当前默认公司</CardTitle>
            <CardDescription>新建项目默认选择</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-lg font-semibold text-slate-900">{defaultCompany?.name || '未设置'}</div>
            <div className="mt-1 text-xs text-slate-500">{defaultCompany?.id || '-'}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>启用公司</CardTitle>
            <CardDescription>业务可选择的公司</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold text-slate-900">{activeCompanies.length}</div></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>停用公司</CardTitle>
            <CardDescription>保留历史，不参与新任务</CardDescription>
          </CardHeader>
          <CardContent><div className="text-3xl font-semibold text-slate-900">{inactiveCompanies.length}</div></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Plus className="h-4 w-4 text-cyan-600" />新增公司</CardTitle>
          <CardDescription>新增后即可在“新建项目”和“知识库”中选择，并上传该公司的专属素材。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-[1fr_260px_180px_120px] lg:items-end">
          <div className="space-y-2">
            <Label>公司名称</Label>
            <Input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="如：示例人力资源服务有限公司" />
          </div>
          <div className="space-y-2">
            <Label>公司ID（可选）</Label>
            <Input value={newId} onChange={(event) => setNewId(event.target.value)} placeholder="如：example-company" />
          </div>
          <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-700">
            <input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} />
            设为默认
          </label>
          <Button onClick={createCompany} disabled={saving}><Plus className="h-4 w-4" />创建</Button>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {activeCompanies.map(renderCompanyRow)}
        {inactiveCompanies.length > 0 && (
          <div className="pt-3">
            <div className="mb-2 text-sm font-medium text-slate-500">已停用</div>
            <div className="space-y-3">{inactiveCompanies.map(renderCompanyRow)}</div>
          </div>
        )}
        {!loading && companies.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">暂无公司</div>
        )}
      </div>
    </div>
  )
}

export default Companies
