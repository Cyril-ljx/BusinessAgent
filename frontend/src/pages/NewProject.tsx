import React, { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { UploadCloud, AlertCircle } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { api, type Company } from '@/api/client';
import { cn } from '@/lib/utils';
const NewProject: React.FC = () => {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [isDragActive, setIsDragActive] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('demo-company');
  const [companyName, setCompanyName] = useState('示例科技服务有限公司');
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const loadCompanies = async () => {
      setLoadingCompanies(true);
      try {
        const res = await api.get<Company[]>('/companies');
        if (cancelled) return;
        const rows = res.data || [];
        setCompanies(rows);
        const selected = rows.find((item) => item.is_default) || rows[0];
        if (selected) {
          setCompanyId(selected.id);
          setCompanyName(selected.name);
        }
      } catch (err) {
        if (!cancelled) {
          setCompanies([
            {
              id: 'demo-company',
              name: '示例科技服务有限公司',
              is_default: true,
              is_active: true,
            },
          ]);
        }
      } finally {
        if (!cancelled) setLoadingCompanies(false);
      }
    };
    loadCompanies();
    return () => {
      cancelled = true;
    };
  }, []);
  // 拖拽处理
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(true);
  }, []);
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
  }, []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      validateAndSetFile(droppedFile);
    }
  }, []);
  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  }, []);
  const validateAndSetFile = (file: File) => {
    setError('');
    const allowedTypes = [
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/msword',
      'application/pdf'
    ];
    if (!allowedTypes.includes(file.type)) {
      setError('仅支持上传 .docx/.doc/.pdf 格式的文件');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setError('文件大小不能超过 50MB');
      return;
    }
    setFile(file);
  };
  // 提交处理
  const handleSubmit = async () => {
    if (!file) {
      setError('请先上传招标书文件');
      return;
    }
    if (!companyName.trim()) {
      setError('请输入投标单位名称');
      return;
    }
    if (!companyId.trim()) {
      setError('请选择知识库公司');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('company_id', companyId);
      formData.append('company_name', companyName);
      const res = await api.post<{ project_id: string }>('/projects/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });
      navigate(`/progress/${res.data.project_id}`);
    } catch (err: any) {
      setError(err.response?.data?.message || '上传失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-neutral-900 mb-2">新建投标项目</h1>
        <p className="text-neutral-600">上传招标书文件，系统将自动解析并生成投标书草稿</p>
      </div>
      <Card className="p-6 shadow-sm">
        {/* 错误提示 */}
        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertCircle className="w-4 h-4 mr-2" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {/* 拖拽上传区 */}
        <div
          className={cn(
            'border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer mb-6',
            isDragActive
              ? 'border-blue-500 bg-blue-50'
              : file
                ? 'border-green-300 bg-green-50'
                : 'border-neutral-300 hover:border-blue-400 hover:bg-neutral-50'
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => document.getElementById('file-upload')?.click()}
        >
          <input
            id="file-upload"
            type="file"
            accept=".docx,.doc,.pdf"
            className="hidden"
            onChange={handleFileSelect}
          />
          <UploadCloud
            className={cn(
              'w-16 h-16 mx-auto mb-4',
              file ? 'text-green-500' : 'text-neutral-400'
            )}
          />
          {file ? (
            <div>
              <p className="text-lg font-medium text-green-700 mb-1">文件已选择</p>
              <p className="text-neutral-600">{file.name}</p>
              <p className="text-sm text-neutral-500 mt-1">
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
          ) : (
            <div>
              <p className="text-lg font-medium text-neutral-700 mb-1">
                拖拽招标书文件到此处，或点击选择文件
              </p>
              <p className="text-sm text-neutral-500 mt-1">
                支持 .docx/.doc/.pdf 格式，最大 50MB
              </p>
            </div>
          )}
        </div>
        {/* 知识库公司选择 */}
        <div className="mb-6">
          <Label htmlFor="knowledge-company" className="text-sm font-medium mb-2 block">
            知识库公司 <span className="text-red-500">*</span>
          </Label>
          <select
            id="knowledge-company"
            value={companyId}
            onChange={(e) => {
              const nextId = e.target.value;
              setCompanyId(nextId);
              const selected = companies.find((item) => item.id === nextId);
              if (selected) setCompanyName(selected.name);
            }}
            disabled={loadingCompanies}
            className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {companies.length === 0 ? (
              <option value="demo-company">示例科技服务有限公司</option>
            ) : (
              companies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))
            )}
          </select>
          <p className="mt-1 text-xs text-neutral-500">
            决定本项目使用哪家公司的证书素材、技术母版和历史章节。
          </p>
        </div>
        {/* 投标单位输入框 */}
        <div className="mb-6">
          <Label htmlFor="company-name" className="text-sm font-medium mb-2 block">
            投标单位名称 <span className="text-red-500">*</span>
          </Label>
          <Input
            id="company-name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="请输入投标单位名称"
            className="h-10"
          />
        </div>
        {/* 提交按钮 */}
        <Button
          className="w-full h-12 text-base font-medium"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? '上传中，请稍候...' : '开始自动生成投标书'}
        </Button>
      </Card>
    </div>
  );
};
export default NewProject;
