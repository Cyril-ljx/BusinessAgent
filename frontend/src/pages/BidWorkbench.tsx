import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  Bold,
  ChevronRight,
  Download,
  FilePlus2,
  FileText,
  ImagePlus,
  Italic,
  LayoutList,
  ListChecks,
  LoaderCircle,
  MessageSquare,
  Pencil,
  Redo2,
  RefreshCw,
  Save,
  Search,
  Send,
  Sparkles,
  Table2,
  Trash2,
  Underline,
  Undo2,
  X,
} from 'lucide-react';

import { api, apiUrl, downloadFromUrl, tenderAPI, type KnowledgeCertificate, type KnowledgeTechSection } from '@/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';

type OutlineNode = {
  id: string;
  name: string;
  required?: boolean;
  has_template?: boolean;
  source?: string;
  render_hook?: Record<string, unknown>;
  children?: OutlineNode[];
};

type MaterialAssignment = {
  node_id?: string;
  materials?: Array<Record<string, unknown>>;
};

type SourceAskCitation = {
  id: string;
  title?: string;
  quote?: string;
  anchor?: string | null;
  page_no?: number | null;
  preview_page_no?: number | null;
};

type SourceAskResponse = {
  answer: string;
  citations?: SourceAskCitation[];
};

type AnalysisFact = {
  id: string;
  group?: string;
  title?: string;
  value?: string;
  detail?: string;
  quote?: string;
  anchor?: Record<string, unknown> | null;
  severity?: string;
  category?: string;
  score?: number;
};

type AnalysisRecommendation = {
  fact_id: string;
  kind: 'scoring' | 'invalidation' | string;
  suggestions: string[];
};

type AnalysisRecommendations = {
  items?: AnalysisRecommendation[];
  generated_at?: string | null;
  used_llm?: boolean;
};

type OutlineResponse = {
  company_id?: string;
  title_info?: Record<string, unknown>;
  outline?: OutlineNode[];
  tender_requirements?: Record<string, unknown>;
  analysis_facts?: Record<string, AnalysisFact[]>;
  analysis_facts_summary?: Record<string, number>;
  analysis_recommendations?: AnalysisRecommendations;
  material_assignments?: MaterialAssignment[];
  generated_sections?: Record<string, string>;
  compliance_report?: Record<string, unknown>;
  render_decisions?: Array<Record<string, unknown>>;
  workflow_stage?: string;
  source_file_path?: string;
  block_index?: Array<Record<string, unknown>>;
  stats?: {
    located_sections?: Array<Record<string, unknown>>;
  };
};

type FlatNode = OutlineNode & { path: string };
type WorkMode = 'analysis' | 'write' | 'verify';
type HelperPanel = 'requirements' | 'materials' | 'ask';
type MaterialPickerTab = 'matched' | 'certificates' | 'tech';
type AskMessage = { id: string; question: string; response?: SourceAskResponse };

class WorkbenchErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="m-6 rounded-2xl border border-red-200 bg-red-50 p-5 text-red-900">
          <div className="font-semibold">编辑工作台渲染失败</div>
          <div className="mt-2 text-sm leading-6">{this.state.error.message}</div>
          <Button className="mt-4" variant="secondary" onClick={() => window.location.reload()}>刷新页面</Button>
        </div>
      );
    }
    return this.props.children;
  }
}

const flattenOutline = (nodes: OutlineNode[] = [], parent = ''): FlatNode[] => {
  const rows: FlatNode[] = [];
  for (const rawNode of Array.isArray(nodes) ? nodes : []) {
    const node = rawNode || {};
    const nodeName = String(node.name || '');
    const nodeId = String(node.id || nodeName || rows.length + 1);
    const path = parent ? `${parent} / ${nodeName}` : nodeName;
    const children = Array.isArray(node.children) ? node.children : [];
    rows.push({ ...node, id: nodeId, name: nodeName, children, path });
    rows.push(...flattenOutline(children, path));
  }
  return rows;
};

const firstLeafId = (nodes: OutlineNode[] = []): string => {
  for (const node of Array.isArray(nodes) ? nodes : []) {
    const children = Array.isArray(node.children) ? node.children : [];
    if (!children.length) return String(node.id || '');
    const child = firstLeafId(children);
    if (child) return child;
  }
  return String(Array.isArray(nodes) ? nodes[0]?.id || '' : '');
};

const escapeHtml = (value: unknown) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;');

const looksLikeHtml = (value: string) => /<\s*(p|div|h[1-6]|table|img|ul|ol|li|strong|b|em|i|u|br)\b/i.test(value);

const normalizeHtmlAssetUrls = (value: string) => String(value || '').replace(
  /(\bsrc\s*=\s*["'])(\/api\/[^"']*)/gi,
  (_match, prefix: string, url: string) => `${prefix}${apiUrl(url)}`,
);

const plainTextToHtml = (value: string) => {
  const text = String(value || '').trim();
  if (!text) return '';
  if (looksLikeHtml(text)) return normalizeHtmlAssetUrls(text);
  return text
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, '<br>')}</p>`)
    .join('');
};

const structuredTextToHtml = (value: string) => {
  const lines = String(value || '').split(/\r?\n/);
  const output: string[] = [];
  const splitRow = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
  const isSeparator = (line: string) => {
    const cells = splitRow(line);
    return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };

  for (let index = 0; index < lines.length;) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    if (line.startsWith('|') && index + 1 < lines.length && isSeparator(lines[index + 1])) {
      const headers = splitRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      output.push(`<table><thead><tr>${headers.map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${escapeHtml(row[cellIndex] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !lines[index].trim().startsWith('|')) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    output.push(`<p>${paragraph.map(escapeHtml).join('<br>')}</p>`);
  }
  return output.join('');
};

const compactText = (value: unknown, max = 180) => {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
};

const textOnly = (value: unknown) => String(value ?? '')
  .replace(/<style[\s\S]*?<\/style>/gi, '')
  .replace(/<script[\s\S]*?<\/script>/gi, '')
  .replace(/<[^>]+>/g, '')
  .replace(/&nbsp;/gi, ' ')
  .replace(/&amp;/gi, '&')
  .replace(/&lt;/gi, '<')
  .replace(/&gt;/gi, '>')
  .replace(/&quot;/gi, '"')
  .replace(/&#39;/gi, "'")
  .replace(/\s+/g, '')
  .trim();

const withoutOutlinePrefix = (value: unknown) => textOnly(value).replace(
  /^(?:第[一二三四五六七八九十百零\d]+[章节部分篇]|[一二三四五六七八九十百零]+|\d+(?:[.．]\d+)*)(?:[、.．:：)）\-—]*)/,
  '',
);

const looksLikeMaterialStubDraft = (draft: string, materials: Array<Record<string, unknown>> = []) => {
  const body = textOnly(draft);
  if (!body || body.length > 260 || !materials.length) return false;
  return materials.some((material) => {
    const source = String(material.source || '');
    const normalizedSource = source === 'knowledge_certificate' ? 'certificate' : source;
    const filePath = textOnly(material.file_path);
    if (filePath && body.includes(filePath)) return true;
    if (normalizedSource === 'tender_template') {
      const note = textOnly(material.note);
      const name = textOnly(material.name || material.source_anchor);
      return Boolean(note && body.includes(note) && (!name || body.includes(name)));
    }
    return normalizedSource === 'certificate'
      && (body.includes('知识库证书') || body.includes('证书图片') || body.includes('素材文件'));
  });
};

const visibleDraftForNode = (node: OutlineNode | undefined, draft: string, materials: Array<Record<string, unknown>> = []) => {
  if (!node) return draft || '';
  const body = textOnly(draft);
  if (!body) return '';
  const name = textOnly(node.name);
  const idAndName = textOnly(`${node.id || ''}${node.name || ''}`);
  const dottedIdAndName = textOnly(`${node.id || ''}.${node.name || ''}`);
  if (
    body === name
    || body === idAndName
    || body === dottedIdAndName
    || withoutOutlinePrefix(body) === withoutOutlinePrefix(name)
  ) return '';
  if (looksLikeMaterialStubDraft(draft, materials)) return '';
  return draft || '';
};

const isTechMasterHookNode = (node: OutlineNode | undefined) => {
  const hook = node?.render_hook;
  return Boolean(
    hook
    && typeof hook === 'object'
    && String(hook.type || '') === 'tech_section'
    && String(hook.copy_mode || '') === 'docx_block',
  );
};

const materialLabel = (material: Record<string, unknown>) => {
  const source = String(material.source || '');
  if (source === 'knowledge_certificate') return `证书资料：${material.category || material.name || ''}`;
  if (source === 'knowledge_tech_section') return `技术方案：${material.chapter_id || material.title || ''}`;
  if (source === 'certificate') return `证书资料：${material.category || material.name || ''}`;
  if (source === 'tech_section') return `技术章节：${material.chapter_id || material.chapter_title || ''}`;
  if (source === 'tech_section_range') return `技术章节：${material.chapter_start || ''} - ${material.chapter_end || ''}`;
  if (source === 'tender_template') {
    return `${isUnresolvedTenderTemplate(material) ? '未定位范本' : '招标范本'}：${material.name || material.source_anchor || ''}`;
  }
  if (source === 'manual') return `待补充：${material.note || ''}`;
  return `${source || '素材'}：${material.name || material.category || material.title || ''}`;
};

const isUnresolvedTenderTemplate = (material: Record<string, unknown>) => (
  String(material.source || '') === 'tender_template'
  && !String(material.content_html || '').trim()
  && String(material.render_status || '') !== 'copied'
  && (
    String(material.note || '').includes('未能定位')
    || (!String(material.source_section_id || '').trim() && !String(material.copy_method || '').trim())
  )
);

const materialTypeLabel = (material: Record<string, unknown>) => {
  const source = String(material.source || '');
  if (source === 'knowledge_certificate') return '证书/图片';
  if (source === 'knowledge_tech_section') return '技术方案';
  if (source.includes('tech')) return '技术方案';
  if (source === 'certificate') return '证照/资质';
  if (source === 'tender_template') return isUnresolvedTenderTemplate(material) ? '未定位' : '招标范本';
  if (source === 'manual') return '待补充';
  return '素材';
};

const materialMatchKey = (material: Record<string, unknown>) => [
  material.source,
  material.id,
  material.chapter_id,
  material.category,
  material.name,
  material.title,
  material.file_path,
  material.source_anchor,
].map((value) => String(value || '').trim()).join('|');

const materialPreview = (material: Record<string, unknown>) => {
  if (String(material.source || '') === 'knowledge_certificate') {
    const fields = [
      material.cert_number && `证书编号：${material.cert_number}`,
      material.issuer && `签发机构：${material.issuer}`,
      material.expire_date && `有效期：${material.expire_date}`,
      material.subcategory,
      material.category,
      material.name,
    ];
    const text = fields.map((item) => String(item || '').trim()).filter(Boolean).join('；') || materialLabel(material);
    return compactText(text, 180);
  }
  const fields = [
    material.preview,
    material.content_preview,
    material.content,
    material.text,
    material.summary,
    material.quote,
    material.snippet,
    material.full_path,
    material.cert_number,
    material.issuer,
    material.expire_date,
    material.note,
    material.reason,
  ];
  const text = fields.map((item) => String(item || '').trim()).find(Boolean) || materialLabel(material);
  return compactText(text, 180);
};

const materialImageUrls = (material: Record<string, unknown>) => {
  const rows = Array.isArray(material.image_urls) ? material.image_urls : [];
  return rows
    .map((item) => {
      if (typeof item === 'string') return apiUrl(item);
      if (item && typeof item === 'object') return apiUrl(String((item as Record<string, unknown>).url || ''));
      return '';
    })
    .filter(Boolean);
};

const materialPreviewCertificates = (material: Record<string, unknown>) => (
  Array.isArray(material.preview_certificates)
    ? material.preview_certificates.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    : []
);

const certificateToMaterial = (item: KnowledgeCertificate) => ({
  source: 'knowledge_certificate',
  id: item.id,
  image_url: apiUrl(`/knowledge/certificates/${item.id}/file`),
  category: item.category,
  subcategory: item.subcategory,
  name: item.name,
  cert_number: item.cert_number,
  issuer: item.issuer,
  file_path: item.file_path,
  file_type: item.file_type,
  expire_date: item.expire_date,
});

const materialThumbnailUrls = (material: Record<string, unknown>) => {
  const direct = [
    String(material.image_url || ''),
    ...materialImageUrls(material),
  ].filter(Boolean);
  const certificateUrls = materialPreviewCertificates(material)
    .map((item) => apiUrl(String(item.image_url || (item.id ? `/knowledge/certificates/${item.id}/file` : ''))))
    .filter(Boolean);
  return Array.from(new Set([...direct, ...certificateUrls].map(apiUrl)));
};

const enrichCertificateCategoryPreview = async (
  material: Record<string, unknown>,
  companyId: string,
) => {
  if (String(material.source || '') !== 'certificate') return material;
  const category = String(material.category || material.name || '').trim();
  if (!category) return material;
  const maxCount = Math.max(1, Math.min(Number(material.max_count || 4) || 4, 8));
  try {
    const rows = await tenderAPI.listCertificates({ category, limit: maxCount, company_id: companyId });
    return {
      ...material,
      preview_certificates: rows.map(certificateToMaterial),
      preview_note: rows.length ? `已找到 ${rows.length} 个知识库文件，导出 Word 会插入这些证书图片。` : '知识库没有找到这个类别的证书文件。',
    };
  } catch (error) {
    return {
      ...material,
      preview_certificates: [],
      preview_note: '证书预览加载失败，请确认后端服务和数据库连接正常。',
    };
  }
};

const enrichMaterialForPreview = async (
  material: Record<string, unknown>,
  companyId: string,
  projectId: string,
) => {
  const source = String(material.source || '');
  if (source === 'certificate') return enrichCertificateCategoryPreview(material, companyId);
  if (source === 'knowledge_certificate') {
    return { ...material, image_url: apiUrl(String(material.image_url || `/knowledge/certificates/${material.id}/file`)) };
  }
  const techSectionId = String(material.id || material.section_id || '').trim();
  if ((source === 'knowledge_tech_section' || source === 'tech_section') && techSectionId && !material.content_preview && !material.content_html && !material.content) {
    const preview = await tenderAPI.previewTechSection(techSectionId, { company_id: companyId }).catch(() => null);
    return preview ? { ...material, ...preview, source } : material;
  }
  if (source === 'tender_template' && projectId && !material.content_html) {
    const preview = await api.post<{ content_html?: string }>(
      `/projects/${projectId}/tender-template-preview`,
      {
        name: String(material.name || material.source_anchor || ''),
        anchor_start: String(material.anchor_start || ''),
        anchor_end: String(material.anchor_end || ''),
        copy_method: String(material.copy_method || ''),
      },
    ).catch(() => null);
    return preview?.data ? { ...material, ...preview.data } : material;
  }
  return material;
};

const blobToDataUrl = (blob: Blob) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ''));
  reader.onerror = () => reject(reader.error || new Error('图片读取失败'));
  reader.readAsDataURL(blob);
});

const inlineRemoteImagesInHtml = async (html: string) => {
  if (!html || typeof DOMParser === 'undefined') return html;
  const document = new DOMParser().parseFromString(html, 'text/html');
  const images = Array.from(document.body.querySelectorAll('img'));
  await Promise.all(images.map(async (img) => {
    const src = apiUrl(String(img.getAttribute('src') || '').trim());
    if (!src || src.startsWith('data:image/')) return;
    img.setAttribute('src', src);
    try {
      const response = await fetch(src, { credentials: 'same-origin' });
      if (!response.ok) return;
      const blob = await response.blob();
      if (!blob.type.startsWith('image/')) return;
      img.setAttribute('src', await blobToDataUrl(blob));
    } catch (error) {
      // Keep the original URL when a preview image cannot be inlined.
    }
  }));
  return document.body.innerHTML;
};

const enrichKnowledgeCertificateImage = async (material: Record<string, unknown>) => {
  if (String(material.source || '') !== 'knowledge_certificate') return material;
  const imageUrl = apiUrl(String(material.image_url || ''));
  if (!imageUrl || imageUrl.startsWith('data:image/')) return material;
  try {
    const response = await fetch(imageUrl, { credentials: 'same-origin' });
    if (!response.ok) return material;
    const blob = await response.blob();
    if (!blob.type.startsWith('image/')) return material;
    const dataUrl = await blobToDataUrl(blob);
    return { ...material, image_url: dataUrl };
  } catch (error) {
    return imageUrl ? { ...material, image_url: imageUrl } : material;
  }
};

const enrichCertificateCategoryForInsert = async (
  material: Record<string, unknown>,
  companyId: string,
) => {
  const enriched = await enrichCertificateCategoryPreview(material, companyId);
  const previews = await Promise.all(
    materialPreviewCertificates(enriched).map((item) => enrichKnowledgeCertificateImage(item)),
  );
  return { ...enriched, preview_certificates: previews };
};

const materialToHtml = (material: Record<string, unknown>) => {
  const title = materialLabel(material);
  const body = materialPreview(material);
  const certificatePreviews = materialPreviewCertificates(material);
  if (certificatePreviews.length) {
    const groups = new Map<string, Array<Record<string, unknown>>>();
    certificatePreviews.forEach((item) => {
      const rawName = String(item.name || item.category || title).trim();
      const groupName = rawName.replace(/_\d+\s*$/, '').trim() || rawName || title;
      groups.set(groupName, [...(groups.get(groupName) || []), item]);
    });
    const groupedHtml = Array.from(groups.entries()).map(([groupName, items]) => {
      const images = items
        .map((item) => apiUrl(String(item.image_url || (item.id ? `/knowledge/certificates/${item.id}/file` : ''))))
        .filter(Boolean)
        .map((url) => `<p><img src="${escapeHtml(url)}" alt="${escapeHtml(groupName)}" /></p>`)
        .join('');
      return `<h3>${escapeHtml(groupName)}</h3>${images}`;
    }).join('');
    return `<h2>${escapeHtml(title)}</h2>${groupedHtml || `<p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`}`;
  }
  if (String(material.source || '') === 'knowledge_certificate') {
    const imageUrl = apiUrl(String(material.image_url || ''));
    if (imageUrl) {
      return `<p><strong>${escapeHtml(title)}</strong></p><p><img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(title)}" /></p>`;
    }
    return `<p><strong>${escapeHtml(title)}</strong></p><p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`;
  }
  if (['knowledge_tech_section', 'tech_section'].includes(String(material.source || ''))) {
    const contentHtml = normalizeHtmlAssetUrls(String(material.content_html || '').trim());
    if (contentHtml) return `<h3>${escapeHtml(title)}</h3>${contentHtml}`;
    const content = String(material.content || material.content_preview || body || '').trim();
    const images = materialImageUrls(material)
      .map((url) => `<p><img src="${escapeHtml(url)}" alt="${escapeHtml(title)}" /></p>`)
      .join('');
    return `<h3>${escapeHtml(title)}</h3>${plainTextToHtml(content) || `<p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`}${images}`;
  }
  if (String(material.source || '') === 'tender_template') {
    const contentHtml = normalizeHtmlAssetUrls(String(material.content_html || '').trim());
    const content = String(material.content_preview || material.content || material.text || '').trim();
    if (contentHtml) return contentHtml;
    if (content) return `<h3>${escapeHtml(String(material.name || material.source_anchor || '招标范本'))}</h3>${structuredTextToHtml(content)}`;
    return `<p><strong>${escapeHtml(title)}</strong></p><p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`;
  }
  if (String(material.source || '') === 'manual') {
    return `<p><strong>${escapeHtml(title)}</strong></p><p>[待补充：${escapeHtml(body)}]</p>`;
  }
  if (String(material.source || '').includes('tech')) {
    return `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`;
  }
  return `<p><strong>${escapeHtml(title)}</strong></p><p>${escapeHtml(body).replace(/\n/g, '<br>')}</p>`;
};

const materialSectionTitle = (material: Record<string, unknown>) => {
  const fullPath = String(material.full_path || '').trim();
  const fromPath = fullPath.split(/[\\/]/).map((part) => part.trim()).filter(Boolean).pop();
  return String(material.title || fromPath || material.name || material.chapter_id || '未命名章节').trim();
};

const materialToSectionContentHtml = (material: Record<string, unknown>) => {
  const contentHtml = normalizeHtmlAssetUrls(String(material.content_html || '').trim());
  if (contentHtml) return contentHtml;
  const content = String(material.content || material.content_preview || materialPreview(material) || '').trim();
  const images = materialImageUrls(material)
    .map((url) => `<p><img src="${escapeHtml(url)}" alt="${escapeHtml(materialSectionTitle(material))}" /></p>`)
    .join('');
  return `${plainTextToHtml(content)}${images}` || materialToHtml(material);
};

const requirementQuote = (item: any) => String(
  item?.requirement?.quote
  || item?.criteria?.quote
  || item?.quote
  || item?.content
  || item?.name
  || item?.item
  || item?.title
  || '',
);

const requirementTitle = (item: any, fallback: string) => String(
  item?.name
  || item?.item
  || item?.title
  || item?.category
  || item?.requirement?.name
  || fallback,
);

const sourceAnchorText = (item: any) => {
  if (!item) return '';
  const anchor = item.source_anchor || item.anchor || item?.requirement?.anchor || item?.criteria?.anchor;
  if (!anchor) return '';
  if (typeof anchor === 'string' || typeof anchor === 'number') return `原文锚点 ${anchor}`;
  if (typeof anchor === 'object') {
    const section = anchor.section_id || anchor.section_title;
    const start = anchor.anchor_start;
    const end = anchor.anchor_end;
    const position = start && end ? `${start}-${end}` : start;
    return [section && `章节 ${section}`, position && `原文锚点 ${position}`].filter(Boolean).join(' · ');
  }
  return `原文锚点 ${String(anchor)}`;
};

const sourceAnchorIds = (item: any): string[] => {
  const anchors: string[] = [];
  const push = (value: unknown) => {
    const text = String(value || '').trim();
    if (text) anchors.push(text);
  };
  const anchor = item?.source_anchor || item?.anchor || item?.requirement?.anchor || item?.criteria?.anchor;
  if (typeof anchor === 'string' || typeof anchor === 'number') {
    push(anchor);
  } else if (anchor && typeof anchor === 'object') {
    push(anchor.anchor_start);
    push(anchor.anchor_end);
    if (Array.isArray(anchor.anchor_blocks)) {
      anchor.anchor_blocks.forEach((block: any) => push(block?.anchor));
    }
  }
  push(item?.anchor_start);
  push(item?.anchor_end);
  return Array.from(new Set(anchors));
};

const sectionAnchorIds = (
  locatedSections: Array<Record<string, unknown>> | undefined,
  item: any,
) => {
  const anchor = item?.source_anchor || item?.anchor || item?.requirement?.anchor || item?.criteria?.anchor;
  const sectionId = String(anchor?.section_id || '').trim();
  if (!sectionId || !Array.isArray(locatedSections)) return [];
  const section = locatedSections.find((row) => String(row?.id || row?.section_id || '').trim() === sectionId);
  return [section?.anchor_start, section?.anchor_end].map((value) => String(value || '').trim()).filter(Boolean);
};

const compactSourceLookupText = (value: unknown) => String(
  value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : value,
)
  .replace(/\s+/g, '')
  .replace(/[^\p{L}\p{N}]/gu, '');

const sourceSearchFragments = (item: any) => {
  const title = requirementTitle(item, '');
  const quote = requirementQuote(item);
  const raw = [title, quote].filter(Boolean).join(' ');
  const compact = compactSourceLookupText(raw);
  const fragments = [
    compact,
    compact.slice(0, 96),
    compact.slice(0, 64),
    compact.slice(0, 36),
  ].filter((text) => text.length >= 4);
  String(raw || '')
    .split(/[\n\r|，,。；;：:、/／\s]+/)
    .map((part) => compactSourceLookupText(part).slice(0, 48))
    .filter((text) => text.length >= 4)
    .forEach((text) => fragments.push(text));
  return Array.from(new Set(fragments)).sort((a, b) => b.length - a.length);
};

const analysisItemLocationKey = (item: any) => String(
  item?.id || `${requirementTitle(item, '')}|${requirementQuote(item)}`,
).replace(/\s+/g, ' ').trim().slice(0, 1200);

const analysisItemQueryText = (item: any) => [
  requirementQuote(item),
  requirementTitle(item, ''),
].filter(Boolean).join('\n').slice(0, 900);

const canLocateAnalysisItem = (item: any) => Boolean(
  item?.preview_page_no
  || sourceAnchorIds(item).length
  || requirementTitle(item, '').trim()
  || requirementQuote(item).trim(),
);

const findBlockLocationForItem = (blockIndex: Array<Record<string, unknown>> | undefined, item: any) => {
  const fragments = sourceSearchFragments(item);
  if (!Array.isArray(blockIndex) || !fragments.length) return null;

  let best: Record<string, unknown> | null = null;
  let bestScore = 0;
  for (const block of blockIndex) {
    const blockText = compactSourceLookupText(block?.text);
    if (blockText.length < 4) continue;

    let score = 0;
    for (const fragment of fragments) {
      if (blockText.includes(fragment)) {
        score = Math.max(score, 1000 + Math.min(fragment.length, 200));
      } else if (fragment.includes(blockText) && blockText.length >= 8) {
        score = Math.max(score, 600 + Math.min(blockText.length, 120));
      }
    }

    if (score > bestScore) {
      bestScore = score;
      best = block;
    }
  }

  return bestScore >= 604 ? best : null;
};

const toRequirementRows = (value: unknown): any[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined && item !== null && String(item).trim() !== '')
      .map(([key, item]) => {
        if (Array.isArray(item)) {
          return item.map((child, index) => (
            typeof child === 'object' && child !== null
              ? { key, index: index + 1, ...(child as Record<string, unknown>) }
              : { name: key, value: child }
          ));
        }
        if (typeof item === 'object' && item !== null) return { key, ...(item as Record<string, unknown>) };
        return { name: key, value: item };
      })
      .flat();
  }
  return [{ value }];
};

const requirementGroups = (
  requirements: Record<string, unknown> | undefined,
  facts?: Record<string, AnalysisFact[]>,
) => {
  const configs = [
    { key: 'basic_info', label: '基础信息', desc: '项目编号、采购人、截止时间、预算等核心元数据', sourceKeys: ['base_info', 'timeline'] },
    { key: 'file_composition', label: '响应文件组成', desc: '投标/响应文件应该包含哪些章节和表单', sourceKeys: ['file_composition'] },
    { key: 'material_checklist', label: '提交材料清单', desc: '需要提供的证明、证书、原件/复印件要求', sourceKeys: ['material_checklist'] },
    { key: 'qualifications', label: '资格审查', desc: '资质门槛、一票否决、供应商资格要求', sourceKeys: ['qualifications'] },
    { key: 'scoring', label: '评审评分', desc: '评分项、客观分、主观分和价格公式', sourceKeys: ['scoring'] },
    { key: 'technical_requirements', label: '技术需求', desc: '服务方案、实施计划、人员团队等技术要求', sourceKeys: ['technical_requirements'] },
    { key: 'business_terms', label: '商务条款', desc: '付款、保证金、违约、售后和合同风险', sourceKeys: ['contract', 'pricing', 'deposit'] },
    { key: 'format_requirements', label: '格式装订', desc: '签字盖章、份数、密封、格式模板要求', sourceKeys: ['format_requirements'] },
    { key: 'invalidation', label: '废标风险', desc: '无效标、否决投标、不予受理等避坑项', sourceKeys: ['invalidation'] },
  ];
  return configs.map(({ key, label, desc, sourceKeys }) => {
    const factRows = Array.isArray(facts?.[key]) ? facts?.[key] || [] : [];
    return {
      key,
      label,
      desc,
      rows: factRows.length ? factRows : sourceKeys.flatMap((sourceKey) => toRequirementRows(requirements?.[sourceKey])),
    };
  });
};

const nodeRequirementRows = (requirements: Record<string, unknown> | undefined, nodeName: string) => {
  const key = nodeName.replace(/\s+/g, '');
  const rows: Array<{ label: string; quote: string }> = [];
  const addIfMatch = (label: string, item: any) => {
    const quote = requirementQuote(item);
    const text = `${requirementTitle(item, '')}${quote}`;
    if (!key || !text.replace(/\s+/g, '').includes(key.slice(0, Math.min(6, key.length)))) return;
    if (quote) rows.push({ label, quote });
  };
  for (const item of ((requirements?.file_composition as any[]) || [])) addIfMatch('文件组成', item);
  for (const item of ((requirements?.material_checklist as any[]) || [])) addIfMatch('提交材料', item);
  for (const item of ((requirements?.scoring as any[]) || [])) addIfMatch('评分要求', item);
  for (const item of ((requirements?.technical_requirements as any[]) || [])) addIfMatch('技术要求', item);
  return rows.slice(0, 8);
};

const collectExpandedAncestorIds = (nodes: OutlineNode[] = [], selectedId = ''): string[] => {
  const walk = (items: OutlineNode[], ancestors: string[]): string[] | null => {
    for (const rawNode of items || []) {
      const node = rawNode || {};
      const nodeId = String(node.id || '');
      const children = Array.isArray(node.children) ? node.children : [];
      if (nodeId === selectedId) return ancestors;
      const found = walk(children, [...ancestors, nodeId]);
      if (found) return found;
    }
    return null;
  };
  return walk(nodes, []) || [];
};

function OutlineTree({
  nodes,
  selectedId,
  onSelect,
  onDelete,
}: {
  nodes: OutlineNode[];
  selectedId: string;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const ancestors = collectExpandedAncestorIds(nodes, selectedId);
    if (!ancestors.length) return;
    setCollapsed((prev) => {
      let changed = false;
      const next = new Set(prev);
      ancestors.forEach((id) => {
        if (next.delete(id)) changed = true;
      });
      return changed ? next : prev;
    });
  }, [nodes, selectedId]);

  const toggleCollapsed = (event: React.SyntheticEvent, nodeId: string) => {
    event.stopPropagation();
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  const render = (items: OutlineNode[], depth = 0): React.ReactNode => (Array.isArray(items) ? items : []).map((rawNode) => {
    const node = rawNode || {};
    const nodeId = String(node.id || '');
    const nodeName = String(node.name || '');
    const children = Array.isArray(node.children) ? node.children : [];
    const selected = nodeId === selectedId;
    const hasChildren = children.length > 0;
    const isCollapsed = collapsed.has(nodeId);
    const isTopLevel = depth === 0;
    return (
      <div key={`${nodeId}-${nodeName}`} className={isTopLevel ? 'rounded-xl bg-slate-50/70 p-1' : ''}>
        <div className="relative">
          {depth > 0 && <span className="absolute bottom-0 left-[-9px] top-0 w-px bg-slate-200" />}
          <button
            type="button"
            onClick={() => onSelect(nodeId)}
            className={`group flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition ${
              selected
                ? 'bg-[#0b1022] text-white shadow-sm'
                : hasChildren
                  ? 'bg-white font-medium text-slate-800 hover:bg-slate-100'
                  : 'text-slate-700 hover:bg-slate-100'
            }`}
            style={{ marginLeft: depth * 14 }}
            title={`${nodeId} ${nodeName}`}
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center">
              {hasChildren ? (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(event) => toggleCollapsed(event, nodeId)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') toggleCollapsed(event, nodeId);
                  }}
                  className={`flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-200 hover:text-slate-700 ${selected ? 'text-slate-200 hover:bg-white/10 hover:text-white' : ''}`}
                  title={isCollapsed ? '展开子目录' : '收起子目录'}
                >
                  <ChevronRight className={`h-4 w-4 transition-transform ${isCollapsed ? '' : 'rotate-90'}`} />
                </span>
              ) : (
                <span className={`h-1.5 w-1.5 rounded-full ${selected ? 'bg-white' : 'bg-slate-300'}`} />
              )}
            </span>
            <span className={`shrink-0 font-mono text-[12px] ${selected ? 'text-slate-300' : hasChildren ? 'text-slate-500' : 'text-blue-500'}`}>{nodeId}</span>
            <span className="min-w-0 flex-1 truncate">{nodeName}</span>
            {hasChildren && <span className={`rounded px-1.5 py-0.5 text-[10px] ${selected ? 'bg-white/10 text-slate-200' : 'bg-slate-100 text-slate-500'}`}>{children.length}</span>}
            {isTechMasterHookNode(node) && <span className={`rounded border px-1 text-[10px] ${selected ? 'border-white/20 bg-white/10 text-slate-100' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>母</span>}
            {node.required && <span className="rounded border border-red-200 bg-red-50 px-1 text-[10px] text-red-600">必</span>}
            {node.has_template && <span className="rounded border border-blue-200 bg-blue-50 px-1 text-[10px] text-blue-600">范</span>}
            {onDelete && depth > 0 && (
              <span
                role="button"
                tabIndex={0}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(nodeId);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.stopPropagation();
                    onDelete(nodeId);
                  }
                }}
                className={`shrink-0 rounded p-1 opacity-0 transition group-hover:opacity-100 ${selected ? 'text-slate-200 hover:bg-white/10 hover:text-white' : 'text-slate-400 hover:bg-red-50 hover:text-red-600'}`}
                title="删除该目录及子目录"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </span>
            )}
          </button>
        </div>
        {hasChildren && !isCollapsed && (
          <div className="ml-5 border-l border-slate-200 pl-2">
            {render(children, depth + 1)}
          </div>
        )}
      </div>
    );
  });
  return <div className="space-y-1.5">{render(nodes)}</div>;
}

function RichEditor({
  nodeId,
  value,
  onChange,
  onOpenMaterialDialog,
}: {
  nodeId: string;
  value: string;
  onChange: (value: string) => void;
  onOpenMaterialDialog: (tab?: MaterialPickerTab) => void;
}) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const savedRangeRef = useRef<Range | null>(null);
  const lastNodeRef = useRef('');
  const lastHtmlRef = useRef('');

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const nextHtml = plainTextToHtml(value);
    const switchedNode = lastNodeRef.current !== nodeId;
    const editorFocused = document.activeElement === editor;
    if (switchedNode || (!editorFocused && nextHtml !== lastHtmlRef.current)) {
      editor.innerHTML = nextHtml;
      lastHtmlRef.current = nextHtml;
      lastNodeRef.current = nodeId;
    }
  }, [nodeId, value]);

  const sync = () => {
    const editor = editorRef.current;
    if (!editor) return;
    const html = editor.innerHTML;
    lastHtmlRef.current = html;
    onChange(html);
  };

  const saveSelection = () => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    const container = range.commonAncestorContainer;
    if (editor.contains(container.nodeType === Node.TEXT_NODE ? container.parentNode : container)) {
      savedRangeRef.current = range.cloneRange();
    }
  };

  const restoreSelection = () => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    const range = savedRangeRef.current;
    if (!editor || !selection || !range) return false;
    const container = range.commonAncestorContainer;
    if (!editor.contains(container.nodeType === Node.TEXT_NODE ? container.parentNode : container)) return false;
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  };

  const openMaterialDialog = (tab: MaterialPickerTab) => {
    saveSelection();
    onOpenMaterialDialog(tab);
  };

  const runCommand = (command: string, commandValue?: string) => {
    editorRef.current?.focus();
    document.execCommand(command, false, commandValue);
    sync();
  };

  const insertHtml = (html: string) => {
    editorRef.current?.focus();
    restoreSelection();
    document.execCommand('insertHTML', false, html);
    sync();
    saveSelection();
  };

  const insertTable = () => {
    const rows = Math.min(Math.max(Number(window.prompt('表格行数', '3') || 3), 1), 20);
    const cols = Math.min(Math.max(Number(window.prompt('表格列数', '3') || 3), 1), 12);
    const body = Array.from({ length: rows }, () => (
      `<tr>${Array.from({ length: cols }, () => '<td><br></td>').join('')}</tr>`
    )).join('');
    insertHtml(`<table><tbody>${body}</tbody></table><p><br></p>`);
  };

  const onImageSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      insertHtml(`<p><img src="${String(reader.result)}" alt="${escapeHtml(file.name)}" /></p><p><br></p>`);
      event.target.value = '';
    };
    reader.readAsDataURL(file);
  };

  const toolbarButton = 'inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-700 shadow-sm hover:bg-slate-50';

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-slate-200 bg-[#f1f5f9]">
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-2">
        <button type="button" className={toolbarButton} onClick={() => runCommand('undo')}><Undo2 className="h-3.5 w-3.5" />撤销</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('redo')}><Redo2 className="h-3.5 w-3.5" />重做</button>
        <span className="mx-1 h-5 w-px bg-slate-200" />
        <button type="button" className={toolbarButton} onClick={() => runCommand('formatBlock', 'H1')}>H1</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('formatBlock', 'H2')}>H2</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('formatBlock', 'H3')}>H3</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('formatBlock', 'P')}>正文</button>
        <span className="mx-1 h-5 w-px bg-slate-200" />
        <button type="button" className={toolbarButton} onClick={() => runCommand('bold')}><Bold className="h-3.5 w-3.5" />加粗</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('italic')}><Italic className="h-3.5 w-3.5" />斜体</button>
        <button type="button" className={toolbarButton} onClick={() => runCommand('underline')}><Underline className="h-3.5 w-3.5" />下划线</button>
        <span className="mx-1 h-5 w-px bg-slate-200" />
        <button type="button" className={toolbarButton} onMouseDown={(event) => { event.preventDefault(); saveSelection(); }} onClick={() => openMaterialDialog('matched')}><FilePlus2 className="h-3.5 w-3.5" />插入资料</button>
        <button type="button" className={toolbarButton} onClick={() => imageInputRef.current?.click()}><ImagePlus className="h-3.5 w-3.5" />本地图片</button>
        <button type="button" className={toolbarButton} onClick={insertTable}><Table2 className="h-3.5 w-3.5" />插入表格</button>
        <input ref={imageInputRef} type="file" accept="image/*" className="hidden" onChange={onImageSelected} />
      </div>
      <div className="flex-1 overflow-auto p-3">
        <div
          ref={editorRef}
          contentEditable
          suppressContentEditableWarning
          onInput={sync}
          onKeyUp={saveSelection}
          onMouseUp={saveSelection}
          onFocus={saveSelection}
          className="mx-auto min-h-[1040px] w-full max-w-[1180px] rounded-sm bg-white px-12 py-8 text-[15px] leading-7 text-slate-900 shadow-sm outline-none empty:before:text-slate-400 empty:before:content-[attr(data-placeholder)] [&_h1]:mb-5 [&_h1]:text-center [&_h1]:text-2xl [&_h1]:font-bold [&_h2]:mb-4 [&_h2]:text-xl [&_h2]:font-bold [&_h3]:mb-3 [&_h3]:text-lg [&_h3]:font-semibold [&_img]:my-4 [&_img]:max-w-full [&_img]:rounded [&_ol]:ml-6 [&_ol]:list-decimal [&_p]:my-2 [&_table]:my-4 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-300 [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-slate-300 [&_th]:bg-slate-50 [&_th]:px-3 [&_th]:py-2 [&_ul]:ml-6 [&_ul]:list-disc"
          data-placeholder="素材渲染后的章节初稿会显示在这里，也可以直接人工编辑。"
        />
      </div>
    </div>
  );
}

function ChapterContentPreview({
  html,
  loading,
  sourceLabel,
  techMasterLinked,
  onEdit,
}: {
  html: string;
  loading: boolean;
  sourceLabel: string;
  techMasterLinked: boolean;
  onEdit: () => void;
}) {
  const hasContent = Boolean(textOnly(html) || /<img\b|<table\b/i.test(html));
  return (
    <div className="flex h-full min-h-0 flex-col bg-[#eef2f7]">
      <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="font-medium text-slate-800">内容预览</span>
          <Badge variant="outline">{sourceLabel}</Badge>
          {techMasterLinked && <span className="truncate text-xs text-emerald-700">导出时保留技术母版原 DOCX 图片、表格和排版</span>}
        </div>
        <Button size="sm" onClick={onEdit}>
          <Pencil className="mr-1 h-4 w-4" />编辑内容
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {loading ? (
          <div className="flex h-full min-h-[360px] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white text-sm text-slate-500">
            正在加载章节渲染内容...
          </div>
        ) : hasContent ? (
          <article
            className="mx-auto min-h-full w-full max-w-[1180px] rounded-sm bg-white px-12 py-9 text-[15px] leading-7 text-slate-900 shadow-sm [&_h1]:mb-5 [&_h1]:text-center [&_h1]:text-2xl [&_h1]:font-bold [&_h2]:mb-4 [&_h2]:text-xl [&_h2]:font-bold [&_h3]:mb-3 [&_h3]:text-lg [&_h3]:font-semibold [&_img]:my-4 [&_img]:max-w-full [&_img]:rounded [&_ol]:ml-6 [&_ol]:list-decimal [&_p]:my-2 [&_table]:my-4 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-300 [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-slate-300 [&_th]:bg-slate-50 [&_th]:px-3 [&_th]:py-2 [&_ul]:ml-6 [&_ul]:list-disc"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-8 text-center">
            <FileText className="h-10 w-10 text-slate-300" />
            <div className="mt-3 font-medium text-slate-700">当前目录还没有可展示的内容</div>
            <div className="mt-1 text-sm leading-6 text-slate-500">点击“编辑内容”后，可以直接编写，也可以从素材库关联证书、图片或技术方案。</div>
            <Button className="mt-4" size="sm" onClick={onEdit}><Pencil className="mr-1 h-4 w-4" />编辑内容</Button>
          </div>
        )}
      </div>
    </div>
  );
}

function MaterialDialog({
  open,
  materials,
  companyId,
  initialTab,
  onClose,
  onInsert,
}: {
  open: boolean;
  materials: Array<Record<string, unknown>>;
  companyId: string;
  initialTab: MaterialPickerTab;
  onClose: () => void;
  onInsert: (html: string, materials?: Array<Record<string, unknown>>) => void | Promise<void>;
}) {
  const [selected, setSelected] = useState<Record<string, unknown>[]>([]);
  const [activeTab, setActiveTab] = useState<MaterialPickerTab>(initialTab);
  const [query, setQuery] = useState('');
  const [loadingKnowledge, setLoadingKnowledge] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState('');
  const [insertError, setInsertError] = useState('');
  const [inserting, setInserting] = useState(false);
  const [certificates, setCertificates] = useState<KnowledgeCertificate[]>([]);
  const [techSections, setTechSections] = useState<KnowledgeTechSection[]>([]);

  const loadKnowledge = useCallback(async (q: string) => {
    setLoadingKnowledge(true);
    setKnowledgeError('');
    try {
      const [certRows, techRows] = await Promise.all([
        tenderAPI.listCertificates({ q: q || undefined, limit: 500, company_id: companyId }),
        tenderAPI.listTechSections({ q: q || undefined, limit: 300, company_id: companyId }),
      ]);
      setCertificates(certRows);
      setTechSections(techRows);
    } catch (error) {
      setKnowledgeError('知识库加载失败，请确认后端服务和数据库连接正常。');
      setCertificates([]);
      setTechSections([]);
    } finally {
      setLoadingKnowledge(false);
    }
  }, [companyId]);

  useEffect(() => {
    if (!open) return;
    setSelected([]);
    setInsertError('');
    setActiveTab(initialTab);
    setQuery('');
    void loadKnowledge('');
  }, [initialTab, loadKnowledge, open]);

  const certificateMaterials = useMemo(() => certificates.map((item) => ({
    source: 'knowledge_certificate',
    id: item.id,
    image_url: apiUrl(`/knowledge/certificates/${item.id}/file`),
    category: item.category,
    subcategory: item.subcategory,
    name: item.name,
    cert_number: item.cert_number,
    issuer: item.issuer,
    file_path: item.file_path,
    file_type: item.file_type,
    expire_date: item.expire_date,
  })), [certificates]);
  const techMaterials = useMemo(() => techSections.map((item) => ({
    ...item,
    source: 'knowledge_tech_section',
    id: item.id,
    chapter_id: item.chapter_id,
    summary: `${item.full_path || item.title || ''}${item.image_count ? `，含图片 ${item.image_count} 张` : ''}${item.table_count ? `，含表格 ${item.table_count} 个` : ''}`,
  })), [techSections]);
  const currentRows: Array<Record<string, unknown>> = activeTab === 'matched' ? materials : activeTab === 'certificates' ? certificateMaterials : techMaterials;

  const materialKey = (material: Record<string, unknown>) => [
    material.source,
    material.id,
    material.chapter_id,
    material.category,
    material.name,
    material.title,
  ].map((value) => String(value || '')).join('|');

  const toggle = (material: Record<string, unknown>) => {
    setSelected((prev) => {
      const key = materialKey(material);
      if (prev.some((item) => materialKey(item) === key)) return prev.filter((item) => materialKey(item) !== key);
      return [...prev, material];
    });
  };

  const insertSelected = async () => {
    if (!selected.length || inserting) return;
    setInserting(true);
    setInsertError('');
    try {
      const enriched = await Promise.all(selected.map(async (material) => {
        if (String(material.source || '') === 'certificate') {
          return enrichCertificateCategoryForInsert(material, companyId);
        }
        if (String(material.source || '') === 'knowledge_certificate') {
          return enrichKnowledgeCertificateImage(material);
        }
        return material;
      }));
      const html = enriched.map(materialToHtml).join('');
      await onInsert(html, enriched);
      onClose();
    } catch (error: any) {
      setInsertError(error?.response?.data?.detail || error?.message || '插入失败，请稍后重试。');
    } finally {
      setInserting(false);
    }
  };

  const tabs: Array<{ key: MaterialPickerTab; label: string; count: number }> = [
    { key: 'matched', label: '当前匹配', count: materials.length },
    { key: 'certificates', label: '证书/图片', count: certificates.length },
    { key: 'tech', label: '技术方案', count: techSections.length },
  ];
  const selectedHasTech = selected.some((material) => String(material.source || '') === 'knowledge_tech_section');

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-5">
      <div className="flex max-h-[86vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <div className="text-base font-semibold">插入资料</div>
            <div className="mt-1 text-sm text-slate-500">技术方案会作为当前章节的下级目录插入；证书/图片建议通过素材匹配参与渲染，本地图片可在编辑器工具栏插入。</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        <div className="border-b bg-slate-50 px-5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white px-3 py-2 text-sm text-slate-600">
            <div className="flex flex-wrap gap-2">
              {tabs.map((tab) => {
                const active = activeTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={`rounded-md px-3 py-1 text-sm transition ${active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-blue-50 hover:text-blue-700'}`}
                  >
                    {tab.label} {tab.count}
                  </button>
                );
              })}
            </div>
            <Badge variant="outline">已选 {selected.length} 项</Badge>
          </div>
          <div className="mt-3 flex gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void loadKnowledge(query);
              }}
              placeholder="搜索证书、资质、技术章节"
              className="h-9 flex-1 rounded-md border border-slate-200 px-3 text-sm outline-none focus:border-blue-400"
            />
            <Button variant="secondary" size="sm" onClick={() => void loadKnowledge(query)} disabled={loadingKnowledge}>
              {loadingKnowledge ? '加载中' : '搜索知识库'}
            </Button>
          </div>
          {knowledgeError && <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{knowledgeError}</div>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-5">
          {loadingKnowledge ? (
            <div className="flex h-56 items-center justify-center rounded-2xl border border-dashed text-sm text-slate-500">
              正在加载知识库素材...
            </div>
          ) : currentRows.length ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {currentRows.map((material, index) => {
                const checked = selected.some((item) => materialKey(item) === materialKey(material));
                const imageUrl = apiUrl(String(material.image_url || materialImageUrls(material)[0] || ''));
                const isTech = String(material.source || '') === 'knowledge_tech_section';
                return (
                  <button
                    key={`${materialLabel(material)}-${index}`}
                    type="button"
                    onClick={() => toggle(material)}
                    className={`flex min-h-[150px] gap-3 rounded-xl border p-3 text-left transition ${checked ? 'border-blue-400 bg-blue-50 ring-2 ring-blue-100' : 'border-slate-200 bg-white hover:border-blue-200 hover:bg-slate-50'}`}
                  >
                    <span className={`mt-1 h-4 w-4 shrink-0 rounded border ${checked ? 'border-blue-500 bg-blue-500' : 'border-slate-300'}`} />
                    {imageUrl && (
                      <span className="flex h-28 w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                        <img
                          src={imageUrl}
                          alt={materialLabel(material)}
                          className="h-full w-full object-contain"
                          loading="lazy"
                        />
                      </span>
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium text-slate-900">{materialLabel(material)}</span>
                        <span className="shrink-0 rounded border border-blue-100 bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600">{materialTypeLabel(material)}</span>
                      </span>
                      <span className="mt-2 line-clamp-3 block text-sm leading-6 text-slate-500">
                        {String(material.cert_number || material.issuer || material.expire_date || '') || materialPreview(material)}
                      </span>
                      {String(material.file_path || '') && <span className="mt-2 block truncate text-xs text-slate-400">{String(material.file_path)}</span>}
                      {isTech && (
                        <span className="mt-2 block text-xs text-slate-400">
                          {String(material.full_path || '')}
                          <br />
                          图 {String(material.image_count ?? 0)} / 表 {String(material.table_count ?? 0)} / 字数 {String(material.char_count ?? 0)}
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex h-56 items-center justify-center rounded-2xl border border-dashed text-sm text-slate-500">
              {activeTab === 'matched' ? '当前章节还没有自动匹配素材，可切换到证书/图片或技术方案从知识库选择。' : '知识库暂无匹配结果。'}
            </div>
          )}
        </div>
        {insertError && (
          <div className="border-t border-red-100 bg-red-50 px-5 py-2 text-sm text-red-700">{insertError}</div>
        )}
        <div className="flex justify-end gap-2 border-t bg-slate-50 px-5 py-4">
          <Button variant="secondary" onClick={onClose} disabled={inserting}>取消</Button>
          <Button onClick={insertSelected} disabled={!selected.length || inserting}>
            {inserting ? '插入中...' : selectedHasTech ? '插入为子目录' : '插入图片/资料'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function MaterialItemCard({
  material,
  onRemove,
  removing,
}: {
  material: Record<string, unknown>;
  onRemove?: (material: Record<string, unknown>) => void;
  removing?: boolean;
}) {
  const thumbnails = materialThumbnailUrls(material).slice(0, 4);
  const previewCertificates = materialPreviewCertificates(material);
  const source = String(material.source || '');
  const unresolvedTemplate = isUnresolvedTenderTemplate(material);
  const note = String(material.preview_note || material.note || '');
  const htmlPreview = normalizeHtmlAssetUrls(String(material.content_html || '').trim());
  const textPreview = materialPreview(material);
  return (
    <div className={`rounded-xl border p-3 text-sm shadow-sm ${unresolvedTemplate ? 'border-amber-200 bg-amber-50/70' : 'border-slate-200 bg-white'}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 truncate font-medium text-slate-900">{materialLabel(material)}</div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`rounded border px-1.5 py-0.5 text-[10px] ${unresolvedTemplate ? 'border-amber-200 bg-amber-100 text-amber-700' : 'border-blue-100 bg-blue-50 text-blue-600'}`}>{materialTypeLabel(material)}</span>
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(material)}
              disabled={removing}
              className="rounded border border-red-100 bg-red-50 px-1.5 py-0.5 text-[10px] text-red-600 hover:bg-red-100 disabled:opacity-60"
            >
              {removing ? '删除中' : '删除'}
            </button>
          )}
        </div>
      </div>
      {thumbnails.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {thumbnails.map((url, index) => {
            const cert = previewCertificates[index];
            return (
              <div key={`${url}-${index}`} className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                <div className="flex h-28 items-center justify-center bg-white">
                  <img src={url} alt={materialLabel(material)} className="h-full w-full object-contain" loading="lazy" />
                </div>
                {cert && (
                  <div className="truncate px-2 py-1 text-[11px] text-slate-500">
                    {String(cert.name || cert.category || `文件 ${index + 1}`)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {source === 'knowledge_tech_section' && htmlPreview ? (
        <div
          className="mt-3 max-h-44 overflow-auto rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600 [&_img]:my-2 [&_img]:max-h-28 [&_img]:max-w-full [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:px-2 [&_th]:border [&_th]:px-2"
          dangerouslySetInnerHTML={{ __html: htmlPreview }}
        />
      ) : (
        <div className="mt-2 line-clamp-4 text-xs leading-5 text-slate-500">{note || textPreview}</div>
      )}
      {source === 'certificate' && !thumbnails.length && (
        <div className="mt-3 rounded-lg border border-dashed border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          {note || '还没有加载到证书图片预览。'}
        </div>
      )}
      {unresolvedTemplate && (
        <div className="mt-3 rounded-lg border border-dashed border-amber-300 bg-white/70 px-3 py-2 text-xs leading-5 text-amber-800">
          这只是判断为“需要招标范本”，还没有定位到可复制的原文正文，因此不应算作成功匹配。
        </div>
      )}
    </div>
  );
}

function HelperDrawer({
  open,
  panel,
  onClose,
  requirementRows,
  materials,
  question,
  askLoading,
  askMessages,
  onQuestionChange,
  onAsk,
  onRemoveMaterial,
  removingMaterialKey,
  onLocateCitation,
  previewFrameSrc,
  sourcePreviewPage,
  sourceLocating,
  sourceLocateError,
}: {
  open: boolean;
  panel: HelperPanel;
  onClose: () => void;
  requirementRows: Array<{ label: string; quote: string }>;
  materials: Array<Record<string, unknown>>;
  question: string;
  askLoading: boolean;
  askMessages: AskMessage[];
  onQuestionChange: (value: string) => void;
  onAsk: () => void;
  onRemoveMaterial: (material: Record<string, unknown>) => void;
  removingMaterialKey?: string;
  onLocateCitation: (citation: SourceAskCitation) => void;
  previewFrameSrc: string;
  sourcePreviewPage: number | null;
  sourceLocating: boolean;
  sourceLocateError: string;
}) {
  if (!open) return null;
  const title = panel === 'requirements' ? '本节要求' : panel === 'materials' ? '匹配资料' : '原文问答';
  const askContent = (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <div className="min-h-0 flex-1 space-y-3 overflow-auto rounded-xl border bg-slate-50 p-3">
        {askMessages.length === 0 && <div className="text-sm text-slate-500">例如：这个章节的原文要求在哪里？投标文件组成有哪些？评分点是什么？</div>}
        {askMessages.map((message) => (
          <div key={message.id} className="space-y-2">
            <div className="ml-auto w-fit max-w-[88%] rounded-2xl bg-slate-950 px-3 py-2 text-sm text-white">{message.question}</div>
            {!message.response && askLoading && (
              <div className="flex w-fit max-w-[88%] items-center gap-2 rounded-2xl border border-blue-100 bg-white px-3 py-2.5 text-sm text-slate-600 shadow-sm">
                <LoaderCircle className="h-4 w-4 animate-spin text-blue-600" />
                <span>正在检索原文并思考...</span>
              </div>
            )}
            {message.response && (
              <div className="rounded-2xl bg-white p-3 text-sm shadow-sm">
                <div className="leading-6">{message.response.answer}</div>
                {(message.response.citations || []).slice(0, 3).map((citation) => (
                  <button
                    key={citation.id}
                    type="button"
                    onClick={() => onLocateCitation(citation)}
                    className="mt-2 w-full rounded-lg bg-slate-50 p-2 text-left text-xs text-slate-500 transition hover:bg-blue-50"
                  >
                    <div className="flex items-center justify-between gap-2 font-medium text-slate-700">
                      <span className="truncate">{citation.title || citation.id}</span>
                      <span className="shrink-0 text-blue-600">
                        {citation.preview_page_no ? `第 ${citation.preview_page_no} 页` : '定位原文'}
                      </span>
                    </div>
                    <div className="mt-1 line-clamp-3">{citation.quote}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Textarea
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') onAsk();
          }}
          placeholder="问原招标文件，例如：目录在哪里？"
          className="min-h-[54px] resize-none"
        />
        <Button onClick={onAsk} disabled={askLoading || !question.trim()} className="self-stretch"><Send className="h-4 w-4" /></Button>
      </div>
    </div>
  );
  if (panel === 'ask') {
    return (
      <div className="fixed inset-0 z-50 bg-slate-950/45 p-2">
        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl bg-[#f4f7fb] shadow-2xl">
          <div className="flex shrink-0 items-center justify-between border-b bg-white px-5 py-3">
            <div>
              <div className="text-lg font-semibold">原文问答</div>
              <div className="mt-1 text-sm text-slate-500">点击右侧引用可在左侧定位招标文件原文。</div>
            </div>
            <button type="button" onClick={onClose} className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-5 w-5" /></button>
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.35fr)_minmax(400px,0.65fr)] gap-3 p-3">
            <Card className="flex min-h-0 gap-0 overflow-hidden border-slate-200 bg-white py-0">
              <div className="flex shrink-0 items-center justify-between border-b px-4 py-2">
                <div className="font-semibold">原文定位</div>
                {sourcePreviewPage && <Badge variant="outline">预览第 {sourcePreviewPage} 页</Badge>}
              </div>
              <div className="min-h-0 flex-1 bg-slate-50 p-1.5">
                {previewFrameSrc ? (
                  <iframe
                    key={previewFrameSrc}
                    title="source-ask-preview"
                    src={previewFrameSrc}
                    className="h-full w-full rounded-lg border border-slate-200 bg-white"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white p-6 text-sm text-slate-500">当前原文件暂不支持预览，请确认源文件已成功上传。</div>
                )}
              </div>
            </Card>
            <Card className="min-h-0 gap-0 overflow-hidden border-slate-200 bg-white py-0">
              {sourceLocating && <div className="shrink-0 border-b bg-blue-50 px-4 py-2 text-sm text-blue-700">正在定位引用原文...</div>}
              {sourceLocateError && <div className="shrink-0 border-b bg-amber-50 px-4 py-2 text-sm text-amber-800">{sourceLocateError}</div>}
              {askContent}
            </Card>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="fixed right-5 top-24 z-40 flex max-h-[calc(100vh-120px)] w-[420px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="font-semibold">{title}</div>
        <button type="button" onClick={onClose} className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {panel === 'requirements' && (
          <div className="space-y-3">
            {requirementRows.length ? requirementRows.map((row, idx) => (
              <div key={idx} className="rounded-xl border bg-slate-50 p-3">
                <div className="text-xs font-medium text-blue-600">{row.label}</div>
                <div className="mt-1 text-sm leading-6 text-slate-700">{row.quote}</div>
              </div>
            )) : <div className="rounded-xl border border-dashed p-4 text-sm text-slate-500">当前章节暂无直接匹配的结构化要求，可用“问原文”查询。</div>}
          </div>
        )}
        {panel === 'materials' && (
          <div className="space-y-3">
            {materials.length ? materials.map((material, idx) => (
              <MaterialItemCard
                key={`${materialMatchKey(material)}-${idx}`}
                material={material}
                onRemove={onRemoveMaterial}
                removing={removingMaterialKey === materialMatchKey(material)}
              />
            )) : <div className="rounded-xl border border-dashed p-4 text-sm text-slate-500">当前章节还没有素材。</div>}
          </div>
        )}
      </div>
    </div>
  );
}

function AnalysisMode({
  requirements,
  facts,
  recommendations,
  previewFrameSrc,
  sourcePreviewPage,
  locating,
  locateError,
  adviceLoading,
  adviceError,
  onLocateItem,
  getLocatePageLabel,
  onGenerateAdvice,
}: {
  requirements?: Record<string, unknown>;
  facts?: Record<string, AnalysisFact[]>;
  recommendations?: AnalysisRecommendations;
  previewFrameSrc: string;
  sourcePreviewPage: number | null;
  locating: boolean;
  locateError: string;
  adviceLoading: boolean;
  adviceError: string;
  onLocateItem: (item: any) => void;
  getLocatePageLabel: (item: any) => string;
  onGenerateAdvice: () => void;
}) {
  const groups = requirementGroups(requirements, facts);
  const firstAvailableKey = groups.find((group) => group.rows.length)?.key || groups[0]?.key || '';
  const [activeKey, setActiveKey] = useState(firstAvailableKey);

  useEffect(() => {
    if (!groups.some((group) => group.key === activeKey)) {
      setActiveKey(firstAvailableKey);
    }
  }, [activeKey, firstAvailableKey, groups]);

  const activeGroup = groups.find((group) => group.key === activeKey) || groups.find((group) => group.rows.length) || groups[0];
  const adviceByFact = new Map(
    (recommendations?.items || []).map((item) => [item.fact_id, item.suggestions]),
  );
  const canGenerateAdvice = activeGroup?.key === 'scoring' || activeGroup?.key === 'invalidation';

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(520px,0.9fr)_minmax(620px,1.1fr)] gap-3">
      <div className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="shrink-0 border-b bg-white px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm text-slate-500">选择分类查看明细，点击页码可在右侧核对原文。</div>
            {activeGroup && <Badge variant="outline">{activeGroup.rows.length} 项</Badge>}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 xl:grid-cols-3">
            {groups.map((group) => {
              const active = activeGroup?.key === group.key;
              return (
                <button
                  key={group.key}
                  type="button"
                  onClick={() => setActiveKey(group.key)}
                  className={`rounded-xl border px-3 py-2 text-left text-sm transition ${active ? 'border-slate-900 bg-slate-950 text-white shadow-sm' : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700'}`}
                >
                  <div className="font-medium">{group.label}</div>
                  <div className={active ? 'text-slate-300' : 'text-slate-400'}>{group.rows.length} 项</div>
                </button>
              );
            })}
          </div>
          {locateError && <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{locateError}</div>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {activeGroup ? (
            <section key={activeGroup.key} id={`analysis-${activeGroup.key}`} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-900">{activeGroup.label}</h3>
                  <p className="mt-1 text-sm text-slate-500">{activeGroup.desc}</p>
                </div>
                {canGenerateAdvice && (
                  <Button size="sm" variant="secondary" onClick={onGenerateAdvice} disabled={adviceLoading || !activeGroup.rows.length}>
                    <Sparkles className={`mr-1 h-3.5 w-3.5 ${adviceLoading ? 'animate-pulse' : ''}`} />
                    {adviceLoading ? '生成中' : '生成建议'}
                  </Button>
                )}
              </div>
              {adviceError && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{adviceError}</div>}
              <div className="mt-4 space-y-2">
                {activeGroup.rows.length ? activeGroup.rows.map((item, index) => {
                  const pageLabel = getLocatePageLabel(item);
                  const suggestions = adviceByFact.get(String(item?.id || '')) || [];
                  return (
                    <div key={index} className="rounded-xl border bg-white p-3 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 font-medium text-blue-700">{requirementTitle(item, `${activeGroup.label} ${index + 1}`)}</div>
                        {sourceAnchorText(item) && <span className="shrink-0 text-xs text-slate-400">{sourceAnchorText(item)}</span>}
                      </div>
                      <div className="mt-1 line-clamp-3 leading-6 text-slate-600">{compactText(requirementQuote(item), 220)}</div>
                      {suggestions.length > 0 && (
                        <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                          <div className="font-medium">分析建议</div>
                          <div className="mt-1 space-y-1 leading-6">
                            {suggestions.map((suggestion, suggestionIndex) => <div key={suggestionIndex}>{suggestion}</div>)}
                          </div>
                        </div>
                      )}
                      <div className="mt-3 flex justify-end">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={locating || !canLocateAnalysisItem(item)}
                          onClick={() => onLocateItem(item)}
                        >
                          <Search className="mr-1 h-3.5 w-3.5" />
                          {pageLabel || '定位原文'}
                        </Button>
                      </div>
                    </div>
                  );
                }) : <div className="rounded-xl border border-dashed bg-white p-4 text-sm text-slate-500">暂无抽取结果。</div>}
              </div>
            </section>
          ) : null}
        </div>
      </div>

      <Card className="flex min-h-0 flex-col overflow-hidden border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="font-semibold">原文对照</div>
          {sourcePreviewPage && <Badge variant="outline">预览第 {sourcePreviewPage} 页</Badge>}
        </div>
        <div className="min-h-0 flex-1 bg-slate-50 p-1.5">
          {previewFrameSrc ? (
            <iframe
              key={previewFrameSrc}
              title="analysis-source-preview"
              src={previewFrameSrc}
              className="h-full min-h-0 w-full rounded-lg border border-slate-200 bg-white"
            />
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-200 bg-white p-6 text-sm text-slate-500">
              当前原文件暂不支持预览，请确认源文件已成功上传。
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

const BidWorkbench: React.FC = () => {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<OutlineResponse | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [mode, setMode] = useState<WorkMode>('write');
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [helperPanel, setHelperPanel] = useState<HelperPanel>('requirements');
  const [helperOpen, setHelperOpen] = useState(false);
  const [materialDialogOpen, setMaterialDialogOpen] = useState(false);
  const [materialDialogInitialTab, setMaterialDialogInitialTab] = useState<MaterialPickerTab>('matched');
  const [question, setQuestion] = useState('');
  const [askLoading, setAskLoading] = useState(false);
  const [askMessages, setAskMessages] = useState<AskMessage[]>([]);
  const [sourcePreviewPage, setSourcePreviewPage] = useState<number | null>(null);
  const [sourceLocateError, setSourceLocateError] = useState('');
  const [sourceLocating, setSourceLocating] = useState(false);
  const [sourceLocations, setSourceLocations] = useState<Record<string, any>>({});
  const [sourceQueryLocations, setSourceQueryLocations] = useState<Record<string, any>>({});
  const [removingMaterialKey, setRemovingMaterialKey] = useState('');
  const [remappingMaterials, setRemappingMaterials] = useState(false);
  const [materialPreviewMap, setMaterialPreviewMap] = useState<Record<string, Record<string, unknown>>>({});
  const [techHookPreview, setTechHookPreview] = useState<KnowledgeTechSection | null>(null);
  const [techHookPreviewLoading, setTechHookPreviewLoading] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [analysisAdviceLoading, setAnalysisAdviceLoading] = useState(false);
  const [analysisAdviceError, setAnalysisAdviceError] = useState('');
  const editorSnapshotRef = useRef<{
    nodeId: string;
    draft: string;
    bootstrappedSource?: 'tech_master' | 'tender_template';
    bootstrappedMaterialSources?: string[];
  } | null>(null);
  const sourceLocateRequestedRef = useRef<Set<string>>(new Set());
  const sourceQueryRequestedRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    const res = await api.get<OutlineResponse>(`/projects/${projectId}/outline`);
    const generatedSections = res.data.generated_sections && typeof res.data.generated_sections === 'object'
      ? res.data.generated_sections
      : {};
    setData(res.data);
    setDrafts(generatedSections);
    setSelectedId((current) => current || firstLeafId(res.data.outline || []));
    setSourceLocations({});
    setSourceQueryLocations({});
    sourceLocateRequestedRef.current.clear();
    sourceQueryRequestedRef.current.clear();
    setLoading(false);
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const flatNodes = useMemo(() => flattenOutline(data?.outline || []), [data?.outline]);
  const selectedNode = flatNodes.find((node) => node.id === selectedId) || flatNodes[0];
  const selectedAssignments = useMemo(() => {
    const assignments = Array.isArray(data?.material_assignments) ? data?.material_assignments || [] : [];
    return assignments.filter((item) => String(item.node_id || '') === selectedNode?.id);
  }, [data?.material_assignments, selectedNode?.id]);
  const selectedMaterials = selectedAssignments.flatMap((item) => (Array.isArray(item.materials) ? item.materials : []));
  const companyId = String(data?.company_id || 'demo-company');
  const techHookSectionId = isTechMasterHookNode(selectedNode)
    ? String(selectedNode?.render_hook?.section_id || '')
    : '';
  const selectedMaterialPreviewKey = selectedMaterials.map(materialMatchKey).join('\n');
  const previewMaterials = useMemo(
    () => selectedMaterials.map((material) => materialPreviewMap[materialMatchKey(material)] || material),
    [materialPreviewMap, selectedMaterials],
  );
  const requirementRows = useMemo(
    () => nodeRequirementRows(data?.tender_requirements, selectedNode?.name || ''),
    [data?.tender_requirements, selectedNode?.name],
  );
  const rawIssues = data?.compliance_report?.issues;
  const complianceIssues = (Array.isArray(rawIssues) ? rawIssues : []).slice(0, 40);
  const currentDraft = visibleDraftForNode(selectedNode, drafts[selectedNode?.id || ''] || '', selectedMaterials);
  const editedCount = flatNodes.filter((node) => visibleDraftForNode(node, drafts[node.id] || '').trim()).length;
  const renderDecisions = Array.isArray(data?.render_decisions) ? data?.render_decisions : [];
  const confirmedCount = renderDecisions.filter((item) => item?.decision || item?.status).length;
  const todoCount = flatNodes.length - editedCount;
  const sourcePreviewUrl = data?.source_file_path && projectId ? apiUrl(`/projects/${projectId}/source-preview`) : '';
  const previewFrameSrc = sourcePreviewUrl
    ? `${sourcePreviewUrl}#page=${sourcePreviewPage || 1}&pagemode=none&navpanes=0&toolbar=1&zoom=55`
    : '';

  useEffect(() => {
    let cancelled = false;
    if (!selectedMaterials.length) {
      setMaterialPreviewMap({});
      return;
    }
    void Promise.all(selectedMaterials.map(async (material) => ({
      key: materialMatchKey(material),
      value: await enrichMaterialForPreview(material, companyId, projectId),
    }))).then((rows) => {
      if (cancelled) return;
      const next: Record<string, Record<string, unknown>> = {};
      rows.forEach((row) => {
        next[row.key] = row.value;
      });
      setMaterialPreviewMap(next);
    });
    return () => {
      cancelled = true;
    };
  }, [companyId, projectId, selectedMaterialPreviewKey]);

  useEffect(() => {
    let cancelled = false;
    if (!techHookSectionId) {
      setTechHookPreview(null);
      setTechHookPreviewLoading(false);
      return;
    }
    setTechHookPreviewLoading(true);
    void tenderAPI.previewTechSection(techHookSectionId, { company_id: companyId })
      .then((preview) => {
        if (!cancelled) setTechHookPreview(preview);
      })
      .catch(() => {
        if (!cancelled) setTechHookPreview(null);
      })
      .finally(() => {
        if (!cancelled) setTechHookPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, techHookSectionId]);

  const materialRenderedHtml = useMemo(
    () => previewMaterials.map(materialToHtml).join(''),
    [previewMaterials],
  );
  const editableTenderTemplateHtml = useMemo(
    () => previewMaterials
      .filter((material) => String(material.source || '') === 'tender_template' && !isUnresolvedTenderTemplate(material))
      .map(materialToHtml)
      .join(''),
    [previewMaterials],
  );
  const techHookRenderedHtml = useMemo(() => {
    if (!techHookPreview) return '';
    return materialToSectionContentHtml({
      ...techHookPreview,
      source: 'knowledge_tech_section',
      id: techHookPreview.id,
    });
  }, [techHookPreview]);
  const chapterPreviewHtml = useMemo(() => {
    const draftHtml = plainTextToHtml(currentDraft);
    if (isTechMasterHookNode(selectedNode)) {
      return draftHtml || techHookRenderedHtml;
    }
    return `${draftHtml}${materialRenderedHtml}`;
  }, [currentDraft, materialRenderedHtml, selectedNode, techHookRenderedHtml]);
  const chapterPreviewSourceLabel = currentDraft.trim()
    ? (previewMaterials.length ? '人工内容 + 匹配素材' : '人工编辑内容')
    : isTechMasterHookNode(selectedNode)
      ? '技术母版原文'
      : previewMaterials.length
        ? '匹配素材'
        : '暂无内容';

  const setCurrentDraft = (value: string) => {
    if (!selectedNode) return;
    setDrafts((prev) => ({ ...prev, [selectedNode.id]: value }));
  };

  const openChapterEditor = () => {
    if (!selectedNode) return;
    const rawDraft = String(drafts[selectedNode.id] || '');
    let bootstrappedSource: 'tech_master' | 'tender_template' | undefined;
    let bootstrappedMaterialSources: string[] = [];
    let editorContent = currentDraft;
    if (!currentDraft.trim() && isTechMasterHookNode(selectedNode) && techHookRenderedHtml.trim()) {
      bootstrappedSource = 'tech_master';
      editorContent = techHookRenderedHtml;
    } else if (!currentDraft.trim() && materialRenderedHtml.trim()) {
      if (editableTenderTemplateHtml.trim()) bootstrappedSource = 'tender_template';
      bootstrappedMaterialSources = Array.from(new Set(
        previewMaterials.map((material) => String(material.source || '').trim()).filter(Boolean),
      ));
      editorContent = materialRenderedHtml;
    }
    editorSnapshotRef.current = {
      nodeId: selectedNode.id,
      draft: rawDraft,
      bootstrappedSource,
      bootstrappedMaterialSources,
    };
    if (editorContent !== currentDraft) {
      setDrafts((prev) => ({ ...prev, [selectedNode.id]: editorContent }));
    }
    setEditorOpen(true);
  };

  const cancelChapterEditor = () => {
    const snapshot = editorSnapshotRef.current;
    if (snapshot) {
      setDrafts((prev) => ({ ...prev, [snapshot.nodeId]: snapshot.draft }));
    }
    editorSnapshotRef.current = null;
    setEditorOpen(false);
  };

  const saveChapterEditor = async () => {
    if (!selectedNode || !projectId) return;
    setSaving(true);
    try {
      const snapshot = editorSnapshotRef.current;
      const persistedContent = await inlineRemoteImagesInHtml(currentDraft);
      await api.put(`/projects/${projectId}/sections/${selectedNode.id}`, {
        content: persistedContent,
        remove_material_sources: snapshot?.bootstrappedMaterialSources || [],
      });
      editorSnapshotRef.current = null;
      setEditorOpen(false);
      await load();
    } finally {
      setSaving(false);
    }
  };

  const insertIntoCurrentDraft = (html: string) => {
    if (!selectedNode) return;
    const next = `${currentDraft || ''}${html}`;
    setDrafts((prev) => ({ ...prev, [selectedNode.id]: next }));
  };

  const insertMaterials = async (html: string, materials: Array<Record<string, unknown>> = []) => {
    if (!selectedNode || !projectId) {
      insertIntoCurrentDraft(html);
      return;
    }
    const techRows = materials.filter((material) => String(material.source || '') === 'knowledge_tech_section');
    const normalRows = materials.filter((material) => String(material.source || '') !== 'knowledge_tech_section');
    let nextCurrentDraft = currentDraft;
    if (normalRows.length) {
      nextCurrentDraft = `${currentDraft || ''}${normalRows.map(materialToHtml).join('')}`;
      setDrafts((prev) => ({ ...prev, [selectedNode.id]: nextCurrentDraft }));
    }
    if (!techRows.length) return;

    if (nextCurrentDraft.trim()) {
      await api.put(`/projects/${projectId}/sections/${selectedNode.id}`, { content: nextCurrentDraft });
    }
    const res = await api.post<{
      outline: OutlineNode[];
      inserted: OutlineNode[];
      generated_sections: Record<string, string>;
      render_decisions?: Array<Record<string, unknown>>;
      stats?: OutlineResponse['stats'];
    }>(`/projects/${projectId}/outline/tech-children`, {
      parent_id: selectedNode.id,
      company_id: String(data?.company_id || 'demo-company'),
      section_ids: techRows.map((material) => String(material.id || '')).filter(Boolean),
    });
    setData((prev) => prev ? {
      ...prev,
      outline: res.data.outline,
      generated_sections: res.data.generated_sections,
      render_decisions: res.data.render_decisions || prev.render_decisions,
      stats: res.data.stats || prev.stats,
    } : prev);
    setDrafts(res.data.generated_sections || {});
    const firstInserted = res.data.inserted?.[0]?.id;
    if (firstInserted) {
      editorSnapshotRef.current = null;
      setEditorOpen(false);
      setSelectedId(String(firstInserted));
    }
  };

  const removeMatchedMaterial = async (material: Record<string, unknown>) => {
    if (!projectId || !selectedNode || !data) return;
    const targetKey = materialMatchKey(material);
    if (!targetKey || removingMaterialKey) return;
    const assignments = Array.isArray(data.material_assignments) ? data.material_assignments : [];
    const nextAssignments = assignments.flatMap((assignment) => {
      if (!assignment || String(assignment.node_id || '') !== selectedNode.id) return [assignment];
      const materials = Array.isArray(assignment.materials) ? assignment.materials : [];
      const nextMaterials = materials.filter((item) => materialMatchKey(item) !== targetKey);
      if (nextMaterials.length === materials.length) return [assignment];
      if (!nextMaterials.length) return [];
      return [{ ...assignment, materials: nextMaterials }];
    });
    setRemovingMaterialKey(targetKey);
    try {
      await api.put(`/projects/${projectId}/material-assignments`, { material_assignments: nextAssignments });
      setData((prev) => prev ? { ...prev, material_assignments: nextAssignments } : prev);
    } finally {
      setRemovingMaterialKey('');
    }
  };

  const saveCurrent = async () => {
    if (!selectedNode || !projectId) return;
    setSaving(true);
    try {
      await api.put(`/projects/${projectId}/sections/${selectedNode.id}`, { content: currentDraft });
      await load();
    } finally {
      setSaving(false);
    }
  };

  const renderWord = async () => {
    if (!projectId) return;
    setRendering(true);
    try {
      await saveCurrent();
      const res = await tenderAPI.renderBlankBid(projectId);
      downloadFromUrl(res.download_url);
      await load();
      setMode('write');
    } finally {
      setRendering(false);
    }
  };

  const remapMaterials = async () => {
    if (!projectId) return;
    setRemappingMaterials(true);
    try {
      await saveCurrent();
      await api.post(`/projects/${projectId}/remap-materials`);
      await load();
    } finally {
      setRemappingMaterials(false);
    }
  };

  const generateAnalysisAdvice = async () => {
    if (!projectId || analysisAdviceLoading) return;
    setAnalysisAdviceLoading(true);
    setAnalysisAdviceError('');
    try {
      const res = await api.post<AnalysisRecommendations>(`/projects/${projectId}/analysis-recommendations`, {});
      setData((prev) => prev ? { ...prev, analysis_recommendations: res.data } : prev);
    } catch (error) {
      const message = error instanceof Error ? error.message : '分析建议生成失败，请稍后重试。';
      setAnalysisAdviceError(message);
    } finally {
      setAnalysisAdviceLoading(false);
    }
  };

  const openHelper = (panel: HelperPanel) => {
    setHelperPanel(panel);
    setHelperOpen(true);
  };

  const openMaterialDialog = (tab: MaterialPickerTab = 'matched') => {
    setMaterialDialogInitialTab(tab);
    setMaterialDialogOpen(true);
  };

  const deleteOutlineNode = async (nodeId: string) => {
    if (!projectId || !nodeId) return;
    const target = flatNodes.find((node) => node.id === nodeId);
    if (!target) return;
    if (!window.confirm(`确定删除「${target.id} ${target.name}」及其下级目录吗？`)) return;
    const res = await api.delete<{
      outline: OutlineNode[];
      removed_ids: string[];
      generated_sections: Record<string, string>;
      material_assignments?: MaterialAssignment[];
      render_decisions?: Array<Record<string, unknown>>;
      stats?: OutlineResponse['stats'];
    }>(`/projects/${projectId}/outline/nodes/${encodeURIComponent(nodeId)}`);
    const removed = new Set((res.data.removed_ids || []).map(String));
    setData((prev) => prev ? {
      ...prev,
      outline: res.data.outline,
      generated_sections: res.data.generated_sections,
      material_assignments: res.data.material_assignments || prev.material_assignments,
      render_decisions: res.data.render_decisions || prev.render_decisions,
      stats: res.data.stats || prev.stats,
    } : prev);
    setDrafts(res.data.generated_sections || {});
    if (removed.has(selectedId)) {
      setSelectedId(firstLeafId(res.data.outline || []));
    }
  };

  const updateTechHook = async (action: 'restore_master' | 'unlink_master') => {
    if (!projectId || !selectedNode || !isTechMasterHookNode(selectedNode) || saving) return;
    if (action === 'unlink_master' && !window.confirm(`确定解除「${selectedNode.id} ${selectedNode.name}」的技术母版关联吗？解除后它会变成普通可编辑章节。`)) {
      return;
    }
    setSaving(true);
    try {
      if (action === 'unlink_master' && currentDraft.trim()) {
        await api.put(`/projects/${projectId}/sections/${selectedNode.id}`, { content: currentDraft });
      }
      const res = await api.put<{
        outline: OutlineNode[];
        generated_sections: Record<string, string>;
        render_decisions?: Array<Record<string, unknown>>;
        stats?: OutlineResponse['stats'];
      }>(`/projects/${projectId}/outline/nodes/${encodeURIComponent(selectedNode.id)}/render-hook`, { action });
      setData((prev) => prev ? {
        ...prev,
        outline: res.data.outline,
        generated_sections: res.data.generated_sections,
        render_decisions: res.data.render_decisions || prev.render_decisions,
        stats: res.data.stats || prev.stats,
      } : prev);
      setDrafts(res.data.generated_sections || {});
      editorSnapshotRef.current = null;
      setEditorOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const locateCandidateAnchors = useCallback((item: any) => {
    const localBlock = findBlockLocationForItem(data?.block_index, item);
    return Array.from(new Set([
      ...sourceAnchorIds(item),
      String(localBlock?.anchor || '').trim(),
      ...sectionAnchorIds(data?.stats?.located_sections, item),
    ].filter(Boolean)));
  }, [data?.block_index, data?.stats?.located_sections]);

  const pageFromItem = useCallback((item: any, extraLocations?: Record<string, any>) => {
    const queryPage = Number(sourceQueryLocations[analysisItemLocationKey(item)]?.preview_page_no || 0);
    if (Number.isFinite(queryPage) && queryPage > 0) return queryPage;

    const directPage = Number(item?.preview_page_no || 0);
    if (Number.isFinite(directPage) && directPage > 0) return directPage;

    const localBlock = findBlockLocationForItem(data?.block_index, item);
    const localPage = Number(localBlock?.preview_page_no || 0);
    if (Number.isFinite(localPage) && localPage > 0) return localPage;

    const mergedLocations = { ...sourceLocations, ...(extraLocations || {}) };
    for (const anchor of locateCandidateAnchors(item)) {
      const location = mergedLocations[anchor];
      const page = Number(location?.preview_page_no || 0);
      if (Number.isFinite(page) && page > 0) return page;
    }
    return 0;
  }, [data?.block_index, locateCandidateAnchors, sourceLocations, sourceQueryLocations]);

  const getLocatePageLabel = useCallback((item: any) => {
    const page = pageFromItem(item);
    return page > 0 ? `预览第 ${page} 页` : '';
  }, [pageFromItem]);

  const preloadAnalysisSourceLocations = useCallback(async () => {
    if (!projectId || !data?.tender_requirements) return;
    const rows = requirementGroups(data.tender_requirements, data.analysis_facts).flatMap((group) => group.rows);
    const anchors = Array.from(new Set(rows.flatMap((item) => locateCandidateAnchors(item))))
      .filter((anchor) => anchor && !sourceLocations[anchor] && !sourceLocateRequestedRef.current.has(anchor))
      .slice(0, 160);
    const queryItems = rows
      .map((item) => ({ id: analysisItemLocationKey(item), text: analysisItemQueryText(item) }))
      .filter((item) => item.id && item.text.replace(/\s+/g, '').length >= 8)
      .filter((item) => !sourceQueryLocations[item.id] && !sourceQueryRequestedRef.current.has(item.id))
      .slice(0, 160);
    if (!anchors.length && !queryItems.length) return;

    anchors.forEach((anchor) => sourceLocateRequestedRef.current.add(anchor));
    queryItems.forEach((item) => sourceQueryRequestedRef.current.add(item.id));
    try {
      const res = await api.post<{ locations?: Record<string, any>; query_locations?: Record<string, any> }>(`/projects/${projectId}/source-locate`, {
        anchors,
        query_items: queryItems,
      });
      setSourceLocations((prev) => ({ ...prev, ...(res.data.locations || {}) }));
      setSourceQueryLocations((prev) => ({ ...prev, ...(res.data.query_locations || {}) }));
    } catch (error) {
      anchors.forEach((anchor) => sourceLocateRequestedRef.current.delete(anchor));
      queryItems.forEach((item) => sourceQueryRequestedRef.current.delete(item.id));
    }
  }, [data?.analysis_facts, data?.tender_requirements, locateCandidateAnchors, projectId, sourceLocations, sourceQueryLocations]);

  useEffect(() => {
    void preloadAnalysisSourceLocations();
  }, [preloadAnalysisSourceLocations]);

  const locateAnalysisItem = async (item: any) => {
    setSourceLocateError('');
    const queryId = analysisItemLocationKey(item);
    const queryText = analysisItemQueryText(item);
    const knownQueryPage = Number(sourceQueryLocations[queryId]?.preview_page_no || 0);
    if (Number.isFinite(knownQueryPage) && knownQueryPage > 0) {
      setSourcePreviewPage(knownQueryPage);
      return;
    }
    const anchors = locateCandidateAnchors(item);
    const hasQuery = queryText.replace(/\s+/g, '').length >= 8;
    if (!projectId || (!anchors.length && !hasQuery)) {
      setSourceLocateError('没有找到可跳转的原文位置。可以试试在“原文问答”里用更具体的关键词检索。');
      return;
    }
    setSourceLocating(true);
    try {
      const queryItems = hasQuery ? [{ id: queryId, text: queryText }] : [];
      const res = await api.post<{ locations?: Record<string, any>; query_locations?: Record<string, any> }>(`/projects/${projectId}/source-locate`, {
        anchors,
        query_items: queryItems,
      });
      const locations = res.data.locations || {};
      const queryLocations = res.data.query_locations || {};
      setSourceLocations((prev) => ({ ...prev, ...locations }));
      setSourceQueryLocations((prev) => ({ ...prev, ...queryLocations }));
      const queryPage = Number(queryLocations[queryId]?.preview_page_no || 0);
      if (Number.isFinite(queryPage) && queryPage > 0) {
        setSourcePreviewPage(queryPage);
        return;
      }
      const located = anchors
        .map((anchor) => locations[anchor])
        .find((location) => location?.preview_page_no);
      const page = Number(located?.preview_page_no || 0);
      if (Number.isFinite(page) && page > 0) {
        setSourcePreviewPage(page);
      } else {
        const fallbackDirectPage = Number(item?.preview_page_no || 0);
        if (Number.isFinite(fallbackDirectPage) && fallbackDirectPage > 0) {
          setSourcePreviewPage(fallbackDirectPage);
          return;
        }
        const fallbackBlock = findBlockLocationForItem(data?.block_index, item);
        const fallbackPage = Number(fallbackBlock?.preview_page_no || 0);
        if (Number.isFinite(fallbackPage) && fallbackPage > 0) {
          setSourcePreviewPage(fallbackPage);
        } else {
          setSourceLocateError('没有解析到可跳转的原文页码，可能是该条来自整理后的摘要或 PDF 文本层质量较差。');
        }
      }
    } catch (error) {
      setSourceLocateError('定位原文失败，请确认源文件预览可用。');
    } finally {
      setSourceLocating(false);
    }
  };

  const locateSourceCitation = async (citation: SourceAskCitation) => {
    if (!projectId) return;
    setSourceLocateError('');

    const directPage = Number(citation.preview_page_no || 0);
    if (Number.isFinite(directPage) && directPage > 0) {
      setSourcePreviewPage(directPage);
      return;
    }

    setSourceLocating(true);
    try {
      const queryId = `source-ask:${citation.id}:${Date.now()}`;
      const quote = String(citation.quote || citation.title || '').trim();
      const res = await api.post<{ locations?: Record<string, any>; query_locations?: Record<string, any> }>(
        `/projects/${projectId}/source-locate`,
        {
          anchors: citation.anchor ? [citation.anchor] : [],
          query_items: quote.replace(/\s+/g, '').length >= 8 ? [{ id: queryId, text: quote }] : [],
        },
      );
      const queryPage = Number(res.data.query_locations?.[queryId]?.preview_page_no || 0);
      const anchorPage = Number(citation.anchor ? res.data.locations?.[citation.anchor]?.preview_page_no : 0);
      const page = queryPage || anchorPage;
      if (Number.isFinite(page) && page > 0) {
        setSourcePreviewPage(page);
      } else {
        setSourceLocateError('该引用没有解析到可跳转的预览页。');
      }
    } catch {
      setSourceLocateError('定位引用原文失败，请确认源文件预览可用。');
    } finally {
      setSourceLocating(false);
    }
  };

  const askSource = async () => {
    const q = question.trim();
    if (!q || askLoading || !projectId) return;
    const id = `${Date.now()}`;
    setQuestion('');
    setAskLoading(true);
    setAskMessages((prev) => [...prev, { id, question: q }]);
    try {
      const res = await api.post<SourceAskResponse>(`/projects/${projectId}/source-ask`, { question: q, top_k: 8 });
      setAskMessages((prev) => prev.map((item) => item.id === id ? { ...item, response: res.data } : item));
    } finally {
      setAskLoading(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-slate-500">正在打开编辑工作台...</div>;
  }

  if (data?.workflow_stage === 'outline_review') {
    return (
      <div className="flex h-full min-h-0 items-center justify-center bg-[#f4f7fb] p-6 text-slate-900">
        <Card className="w-full max-w-2xl border-blue-100 bg-white p-6 shadow-sm">
          <div className="inline-flex items-center rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
            目录确认阶段
          </div>
          <h1 className="mt-4 text-2xl font-semibold">先确认目录并匹配素材，再进入编辑工作台</h1>
          <p className="mt-3 text-sm leading-6 text-slate-600">
            当前项目还没有生成素材分配和章节正文。请回到目录页检查目录结构，确认后运行素材匹配，系统渲染出初稿后再进入这里做人机协同编辑。
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={() => navigate(`/outline/${projectId}`)}>
              返回目录确认
            </Button>
            <Button variant="secondary" onClick={load}>
              <RefreshCw className="mr-1 h-4 w-4" />刷新状态
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#f4f7fb] text-slate-900">
      <div className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs text-blue-600"><Sparkles className="h-4 w-4" />人机协同编辑工作台</div>
            <h1 className="mt-1 truncate text-xl font-semibold">{String(data?.title_info?.title || data?.title_info?.project_name || '投标文件编辑')}</h1>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-md border border-green-200 bg-green-50 px-2 py-1 text-xs text-green-700">已确认 {confirmedCount}</span>
            <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700">编写中 {editedCount}</span>
            <span className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">待补资料 {selectedMaterials.filter((m) => String(m.source || '') === 'manual').length}</span>
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">未生成 {Math.max(todoCount, 0)}</span>
            <Button variant="secondary" onClick={() => navigate(`/outline/${projectId}`)}>目录管理</Button>
            <Button variant="secondary" onClick={load}><RefreshCw className="mr-1 h-4 w-4" />刷新</Button>
            <Button variant="secondary" onClick={remapMaterials} disabled={remappingMaterials || saving || rendering}>
              <RefreshCw className={`mr-1 h-4 w-4 ${remappingMaterials ? 'animate-spin' : ''}`} />{remappingMaterials ? '匹配中' : '重跑素材匹配'}
            </Button>
            <Button onClick={renderWord} disabled={rendering}><Download className="mr-1 h-4 w-4" />{rendering ? '生成中' : '导出 Word'}</Button>
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-slate-100 px-5">
          <div className="flex items-center gap-1">
            {[
              ['analysis', '解析', FileText],
              ['write', '编写', LayoutList],
            ].map(([key, label, Icon]) => {
              const ActiveIcon = Icon as typeof FileText;
              const active = key === 'analysis' ? analysisOpen : mode === key;
              return (
                <button
                  key={String(key)}
                  type="button"
                  onClick={() => {
                    if (key === 'analysis') {
                      setAnalysisOpen(true);
                      return;
                    }
                    setMode(key as WorkMode);
                  }}
                  className={`flex items-center gap-1.5 border-b-2 px-5 py-3 text-sm font-medium transition ${active ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-600 hover:text-slate-900'}`}
                >
                  <ActiveIcon className="h-4 w-4" />{String(label)}
                </button>
              );
            })}
          </div>
          {mode === 'write' && selectedNode && (
            <div className="flex min-w-0 items-center gap-3 text-sm">
              <span className="text-slate-400">当前处理</span>
              <ChevronRight className="h-4 w-4 text-slate-300" />
              <span className="max-w-[560px] truncate font-medium">{selectedNode.id} {selectedNode.name}</span>
              <span className="text-slate-400">章节类型</span>
              <Badge variant="outline">{selectedNode.has_template ? '固定格式' : '可编辑'}</Badge>
              <Button variant="secondary" size="sm" onClick={() => openHelper('requirements')}>本节编写需求</Button>
              <Button variant="secondary" size="sm" onClick={() => openHelper('materials')}>匹配到的资料</Button>
              <Button variant="secondary" size="sm" onClick={() => openHelper('ask')}>问原文</Button>
            </div>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 px-3 pb-3 pt-1">
        {mode === 'write' && (
          <div className="grid h-full min-h-0 grid-cols-[320px_minmax(780px,1fr)] gap-3">
            <Card className="gap-0 overflow-hidden border-slate-200 bg-white py-0">
              <div className="border-b px-4 py-3">
                <div className="flex items-center gap-2 font-semibold"><ListChecks className="h-4 w-4" />标书目录</div>
                <div className="mt-1 text-xs text-slate-500">保留父子级结构，点击章节编辑正文</div>
              </div>
              <div className="h-[calc(100%-58px)] overflow-auto p-3">
                <OutlineTree
                  nodes={data?.outline || []}
                  selectedId={selectedNode?.id || ''}
                  onSelect={setSelectedId}
                  onDelete={deleteOutlineNode}
                />
              </div>
            </Card>

            <Card className="flex min-w-0 flex-col gap-0 overflow-hidden border-slate-200 bg-white py-0">
              <div className="flex items-start justify-between gap-4 border-b px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-slate-400">章节内容预览</div>
                  <div className="truncate text-lg font-semibold">{selectedNode ? `${selectedNode.id} ${selectedNode.name}` : '未选择章节'}</div>
                </div>
                <div className="flex max-w-[52%] flex-wrap items-center justify-end gap-2">
                  {selectedNode?.required && <Badge className="border-red-200 bg-red-50 text-red-700">必填</Badge>}
                  {isTechMasterHookNode(selectedNode) && <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">技术母版</Badge>}
                  {selectedNode?.has_template && <Badge className="border-blue-200 bg-blue-50 text-blue-700">范本</Badge>}
                  {currentDraft.trim() ? (
                    <Badge className="border-green-200 bg-green-50 text-green-700">已编辑</Badge>
                  ) : isTechMasterHookNode(selectedNode) ? (
                    <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">已关联母版</Badge>
                  ) : previewMaterials.length ? (
                    <Badge className="border-blue-200 bg-blue-50 text-blue-700">已匹配素材</Badge>
                  ) : (
                    <Badge variant="outline">待编辑</Badge>
                  )}
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <ChapterContentPreview
                  html={chapterPreviewHtml}
                  loading={techHookPreviewLoading && isTechMasterHookNode(selectedNode) && !currentDraft.trim()}
                  sourceLabel={chapterPreviewSourceLabel}
                  techMasterLinked={isTechMasterHookNode(selectedNode) && !currentDraft.trim()}
                  onEdit={openChapterEditor}
                />
              </div>
            </Card>
          </div>
        )}

        {mode === 'verify' && (
          <div className="grid h-full grid-cols-[minmax(0,1fr)_360px] gap-3">
            <Card className="overflow-auto border-slate-200 bg-white p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className="text-lg font-semibold">智能核验结果</div>
                  <div className="mt-1 text-sm text-slate-500">后续可以扩展为逐条定位招标文件与标书正文。</div>
                </div>
                <Button variant="secondary" onClick={() => openHelper('ask')}><MessageSquare className="mr-1 h-4 w-4" />问原文</Button>
              </div>
              <div className="space-y-3">
                {complianceIssues.length ? complianceIssues.map((issue, idx) => (
                  <div key={idx} className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                    <div className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" />{String(issue.title || issue.type || `核验项 ${idx + 1}`)}</div>
                    <div className="mt-1 leading-6">{String(issue.message || issue.detail || issue.description || '')}</div>
                  </div>
                )) : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-slate-500">暂无核验问题。</div>}
              </div>
            </Card>
            <Card className="overflow-auto border-slate-200 bg-white p-5">
              <div className="font-semibold">核验说明</div>
              <div className="mt-3 space-y-3 text-sm leading-6 text-slate-600">
                <p>这里用于展示生成标书后的风险项，例如占位符残留、范本未回填、资质未响应等。</p>
                <p>业务人员可以结合左侧核验项和“问原文”确认是否需要修改。</p>
              </div>
            </Card>
          </div>
        )}
      </div>

      {analysisOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/45 p-1.5 md:p-2">
          <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl bg-[#f4f7fb] shadow-2xl">
            <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5 py-2">
              <div className="flex items-baseline gap-3">
                <div className="text-lg font-semibold">投标分析总览</div>
                <div className="text-sm text-slate-500">左侧查看抽取结果，右侧核对招标文件原文。</div>
              </div>
              <button
                type="button"
                onClick={() => setAnalysisOpen(false)}
                className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                aria-label="关闭解析弹窗"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 p-2">
              <AnalysisMode
                requirements={data?.tender_requirements}
                facts={data?.analysis_facts}
                recommendations={data?.analysis_recommendations}
                previewFrameSrc={previewFrameSrc}
                sourcePreviewPage={sourcePreviewPage}
                locating={sourceLocating}
                locateError={sourceLocateError}
                adviceLoading={analysisAdviceLoading}
                adviceError={analysisAdviceError}
                onLocateItem={locateAnalysisItem}
                getLocatePageLabel={getLocatePageLabel}
                onGenerateAdvice={generateAnalysisAdvice}
              />
            </div>
          </div>
        </div>
      )}

      {editorOpen && selectedNode && (
        <div className="fixed inset-0 z-40 bg-slate-950/45 p-2 md:p-3">
          <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex shrink-0 items-center justify-between gap-4 border-b border-slate-200 px-5 py-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>编辑章节内容</span>
                  {isTechMasterHookNode(selectedNode) && (
                    <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">技术母版</Badge>
                  )}
                  {previewMaterials.length > 0 && (
                    <button
                      type="button"
                      onClick={() => openHelper('materials')}
                      className="rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-blue-700 hover:bg-blue-100"
                    >
                      已匹配资料 {previewMaterials.length} 项
                    </button>
                  )}
                </div>
                <div className="mt-1 truncate text-lg font-semibold">{selectedNode.id} {selectedNode.name}</div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                {isTechMasterHookNode(selectedNode) && currentDraft.trim() && (
                  <Button variant="secondary" size="sm" onClick={() => void updateTechHook('restore_master')} disabled={saving}>
                    <RefreshCw className="mr-1 h-4 w-4" />恢复母版复制
                  </Button>
                )}
                {isTechMasterHookNode(selectedNode) && (
                  <Button variant="secondary" size="sm" onClick={() => void updateTechHook('unlink_master')} disabled={saving}>
                    <X className="mr-1 h-4 w-4" />{saving ? '处理中...' : '解除母版关联'}
                  </Button>
                )}
                <Button variant="secondary" onClick={cancelChapterEditor} disabled={saving}>取消</Button>
                <Button onClick={() => void saveChapterEditor()} disabled={saving}>
                  <Save className="mr-1 h-4 w-4" />{saving ? '保存中' : '保存并返回预览'}
                </Button>
              </div>
            </div>
            {isTechMasterHookNode(selectedNode) && (
              <div className="shrink-0 border-b border-emerald-100 bg-emerald-50 px-5 py-2 text-xs leading-5 text-emerald-800">
                编辑并保存后，本章使用人工内容覆盖技术母版；直接取消则继续按原 DOCX 块导出，图片、表格和复杂排版不会被改写。
              </div>
            )}
            {editorSnapshotRef.current?.bootstrappedSource === 'tender_template' && (
              <div className="shrink-0 border-b border-blue-100 bg-blue-50 px-5 py-2 text-xs leading-5 text-blue-800">
                当前内容来自招标原文范本。取消不会改变原范本；保存后本章将转为人工编辑内容，并停止重复复制原范本。
              </div>
            )}
            <div className="min-h-0 flex-1">
              <RichEditor
                nodeId={selectedNode.id}
                value={currentDraft}
                onChange={setCurrentDraft}
                onOpenMaterialDialog={openMaterialDialog}
              />
            </div>
          </div>
        </div>
      )}

      <HelperDrawer
        open={helperOpen}
        panel={helperPanel}
        onClose={() => setHelperOpen(false)}
        requirementRows={requirementRows}
        materials={previewMaterials}
        question={question}
        askLoading={askLoading}
        askMessages={askMessages}
        onQuestionChange={setQuestion}
        onAsk={askSource}
        onRemoveMaterial={(material) => { void removeMatchedMaterial(material); }}
        removingMaterialKey={removingMaterialKey}
        onLocateCitation={(citation) => { void locateSourceCitation(citation); }}
        previewFrameSrc={previewFrameSrc}
        sourcePreviewPage={sourcePreviewPage}
        sourceLocating={sourceLocating}
        sourceLocateError={sourceLocateError}
      />

      <MaterialDialog
        open={materialDialogOpen}
        materials={previewMaterials}
        companyId={companyId}
        initialTab={materialDialogInitialTab}
        onClose={() => setMaterialDialogOpen(false)}
        onInsert={insertMaterials}
      />
    </div>
  );
};

const BidWorkbenchPage: React.FC = () => (
  <WorkbenchErrorBoundary>
    <BidWorkbench />
  </WorkbenchErrorBoundary>
);

export default BidWorkbenchPage;
