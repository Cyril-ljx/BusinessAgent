import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  Building,
  CheckCircle2,
  Download,
  FileText,
  ListChecks,
  LoaderCircle,
  MapPin,
  MessageSquare,
  Plus,
  Redo2,
  Save,
  Undo2,
  User,
} from 'lucide-react';

import { api, apiUrl, downloadFromUrl, tenderAPI } from '@/api/client';
import { MaterialAssignment } from '@/components/MaterialPanel';
import { OutlineEditor } from '@/components/OutlineEditor';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import {
  addUidsToNodes,
  getInitialState,
  outlineEditorReducer,
  OutlineNode as OutlineNodeType,
  removeUidsFromNodes,
  traverseNodes,
} from '@/lib/outline-editor';

type RawOutlineNode = Omit<OutlineNodeType, 'uid'>;

type RequirementAnchor = {
  section_id?: string | null;
  section_title?: string | null;
  anchor_start?: string | null;
  anchor_end?: string | null;
  anchor_blocks?: Array<{ anchor: string; kind?: string; text?: string }>;
};

type BlockIndexItem = {
  anchor: string;
  kind?: string;
  text?: string;
  page_no?: number | null;
  page_no_end?: number | null;
  preview_page_no?: number | null;
  preview_page_no_end?: number | null;
};

type ResolvedAnchorLocation = {
  anchor: string;
  kind?: string;
  text?: string;
  page_no?: number | null;
  page_no_end?: number | null;
  preview_page_no?: number | null;
  preview_page_no_end?: number | null;
};

type SourceAskCitation = {
  id: string;
  title?: string;
  quote?: string;
  anchor?: string | null;
  page_no?: number | null;
  preview_page_no?: number | null;
  score?: number;
};

type SourceAskResponse = {
  answer: string;
  citations: SourceAskCitation[];
  confidence: 'low' | 'medium' | 'high' | string;
  used_llm: boolean;
};

type SourceAskMessage = {
  id: string;
  question: string;
  response?: SourceAskResponse;
};

type LocatedSectionSummary = {
  id?: string;
  title?: string;
  relevance?: string;
  anchor_start?: string | null;
  anchor_end?: string | null;
};

type RequirementAtom = {
  value?: unknown;
  quote?: string;
  anchor?: RequirementAnchor | null;
  severity?: string;
};

type BaseInfoRequirements = {
  project_name?: RequirementAtom | null;
  tender_no?: RequirementAtom | null;
  purchaser?: RequirementAtom | null;
  agency?: RequirementAtom | null;
  submission_deadline?: RequirementAtom | null;
  bid_open_time?: RequirementAtom | null;
  bid_validity_period?: RequirementAtom | null;
  document_title?: RequirementAtom | null;
};

type DepositRequirements = {
  required?: RequirementAtom | null;
  amount?: RequirementAtom | null;
  currency?: RequirementAtom | null;
  payment_method?: RequirementAtom | null;
  payment_deadline?: RequirementAtom | null;
  refund_conditions?: RequirementAtom[];
  forfeiture_conditions?: RequirementAtom[];
};

type PricingRequirement = {
  highest_limit?: RequirementAtom | null;
  quotation_method?: RequirementAtom | null;
  price_components?: RequirementAtom[];
  tax_rules?: RequirementAtom[];
  abnormal_price_rules?: RequirementAtom[];
};

type FileCompositionItem = {
  name?: string;
  required?: boolean;
  order?: number | null;
  template_ref?: string | null;
  requirement?: RequirementAtom | null;
};

type FormatRequirementItem = {
  name?: string;
  requirement?: RequirementAtom | null;
  template_ref?: string | null;
};

type QualificationRequirementItem = {
  name?: string;
  requirement?: RequirementAtom | null;
};

type TechnicalRequirementItem = {
  name?: string;
  required_value?: RequirementAtom | null;
};

type ScoringRequirementItem = {
  score_type?: string | null;
  category?: string;
  item?: string;
  score?: number | null;
  criteria?: RequirementAtom | null;
};

type ScoringOverviewGroup = {
  score_type?: string;
  total_score?: number | null;
  items?: ScoringRequirementItem[];
};

type ScoringOverview = {
  total_score?: number | null;
  groups?: ScoringOverviewGroup[];
};

type InvalidationRequirementItem = {
  condition?: string;
  quote?: string;
  anchor?: RequirementAnchor | null;
  severity?: string;
};

type TimelineRequirementItem = {
  name?: string;
  action?: string | null;
  time?: RequirementAtom | null;
  fatal_if_missed?: boolean;
  severity?: string;
};

type MaterialChecklistItem = {
  name?: string;
  original?: boolean | null;
  copy_sealed?: boolean | null;
  count?: number | null;
  required?: boolean;
  requirement?: RequirementAtom | null;
};

type ContractRequirements = {
  service_period?: RequirementAtom | null;
  performance_bond?: RequirementAtom | null;
  payment_terms?: RequirementAtom[];
  acceptance_rules?: RequirementAtom[];
  penalty_clauses?: RequirementAtom[];
  other_risks?: RequirementAtom[];
};

type TenderRequirements = {
  base_info?: BaseInfoRequirements;
  deposit?: DepositRequirements;
  pricing?: PricingRequirement;
  timeline?: TimelineRequirementItem[];
  file_composition?: FileCompositionItem[];
  format_requirements?: FormatRequirementItem[];
  qualifications?: QualificationRequirementItem[];
  technical_requirements?: TechnicalRequirementItem[];
  scoring?: ScoringRequirementItem[];
  scoring_overview?: ScoringOverview;
  invalidation?: InvalidationRequirementItem[];
  material_checklist?: MaterialChecklistItem[];
  contract?: ContractRequirements;
  [key: string]: unknown;
};

type RetrievalHit = {
  source?: string;
  name?: string;
  category?: string;
  chapter_id?: string;
  full_path?: string;
  confidence?: number;
  reason?: string;
};

type RetrievalNodeSummary = {
  node_id: string;
  node_name?: string;
  has_assignment?: boolean;
  material_count?: number;
  material_fact_count?: number;
  confidence?: number;
  retrieval_method?: string;
  top_hits?: RetrievalHit[];
};

type RetrievalSummary = {
  nodes?: RetrievalNodeSummary[];
  stats?: {
    total_nodes?: number;
    assigned_nodes?: number;
    fact_nodes?: number;
    high_confidence_nodes?: number;
  };
};

interface TitleInfo {
  title: string;
  project_name: string;
  purchaser: string;
  tender_no?: string;
}

const OutlineReview: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const [state, dispatch] = useReducer(outlineEditorReducer, getInitialState());
  const [loading, setLoading] = useState(true);
  const [titleInfo, setTitleInfo] = useState<TitleInfo | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [materialAssignments, setMaterialAssignments] = useState<MaterialAssignment[]>([]);
  const [retrievalSummary, setRetrievalSummary] = useState<RetrievalSummary>({});
  const [tenderRequirements, setTenderRequirements] = useState<TenderRequirements>({});
  const [workflowStage, setWorkflowStage] = useState('');
  const [analysisDialogOpen, setAnalysisDialogOpen] = useState(false);
  const [sourceAskDialogOpen, setSourceAskDialogOpen] = useState(false);
  const [outlinePasteDialogOpen, setOutlinePasteDialogOpen] = useState(false);
  const [analysisTab, setAnalysisTab] = useState<'base' | 'qualification' | 'scoring' | 'format' | 'invalid' | 'submit_contract'>('base');
  const [selectedMaterialIndex, setSelectedMaterialIndex] = useState<number>(0);

  const [renderLoading, setRenderLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [confirmMessage, setConfirmMessage] = useState('');
  const [hasRendered, setHasRendered] = useState(false);
  const [stats, setStats] = useState({ total: 0, required: 0, hasTemplate: 0, maxLevel: 0 });
  const [sourcePreviewUrl, setSourcePreviewUrl] = useState('');
  const [sourcePreviewPage, setSourcePreviewPage] = useState<number | null>(null);
  const [sourceQuestion, setSourceQuestion] = useState('');
  const [sourceAskMessages, setSourceAskMessages] = useState<SourceAskMessage[]>([]);
  const [sourceAskLoading, setSourceAskLoading] = useState(false);
  const [sourceAskError, setSourceAskError] = useState('');
  const [outlinePasteText, setOutlinePasteText] = useState('');
  const [outlinePasteLoading, setOutlinePasteLoading] = useState(false);
  const [outlinePasteError, setOutlinePasteError] = useState('');
  const [blockIndex, setBlockIndex] = useState<BlockIndexItem[]>([]);
  const [locatedSections, setLocatedSections] = useState<LocatedSectionSummary[]>([]);
  const [anchorLocations, setAnchorLocations] = useState<Record<string, ResolvedAnchorLocation>>({});
  const anchorRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const sourceLocateRequestedRef = useRef<Set<string>>(new Set());

  const renderedStorageKey = projectId ? `tender-rendered:${projectId}` : '';

  useEffect(() => {
    if (!renderedStorageKey) return;
    setHasRendered(localStorage.getItem(renderedStorageKey) === '1');
  }, [renderedStorageKey]);

  useEffect(() => {
    if (!state.isDirty || loading || confirmLoading || !projectId) return;
    const saveTimer = setTimeout(async () => {
      dispatch({ type: 'SAVE_START' });
      try {
        await api.put(`/projects/${projectId}/outline`, { outline: removeUidsFromNodes(state.outline) });
        dispatch({ type: 'SAVE_SUCCESS' });
        setWorkflowStage('outline_review');
        setMaterialAssignments([]);
        setRetrievalSummary({});
      } catch {
        dispatch({ type: 'SAVE_FAILED' });
      }
    }, 1500);

    return () => clearTimeout(saveTimer);
  }, [state.isDirty, state.outline, loading, confirmLoading, projectId]);

  const fetchOutline = async () => {
    if (!projectId) return;
    try {
      const res = await api.get<{
        title_info: TitleInfo;
        outline: RawOutlineNode[];
        material_assignments?: MaterialAssignment[];
        retrieval_summary?: RetrievalSummary;
        generated_sections?: Record<string, string>;
        tender_requirements?: TenderRequirements;
        workflow_stage?: string;
        source_file_path?: string;
        block_index?: BlockIndexItem[];
        stats?: { located_sections?: LocatedSectionSummary[] };
        warnings: string[];
      }>(`/projects/${projectId}/outline`);

      setTitleInfo(res.data.title_info);
      setWarnings(res.data.warnings || []);
      setMaterialAssignments(res.data.material_assignments || []);
      setRetrievalSummary(res.data.retrieval_summary || {});
      setTenderRequirements(res.data.tender_requirements || {});
      setWorkflowStage(res.data.workflow_stage || '');
      setSourcePreviewUrl(res.data.source_file_path ? apiUrl(`/projects/${projectId}/source-preview`) : '');
      setBlockIndex(res.data.block_index || []);
      setLocatedSections(res.data.stats?.located_sections || []);

      const outlineWithUids = addUidsToNodes(res.data.outline);
      dispatch({ type: 'LOAD', payload: outlineWithUids });
      calculateStats(outlineWithUids);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOutline();
  }, [projectId]);

  useEffect(() => {
    sourceLocateRequestedRef.current = new Set();
  }, [projectId]);

  useEffect(() => {
    const qp = new URLSearchParams(window.location.search);
    const anchor = qp.get('anchor');
    if (!anchor || !blockIndex.length) return;
    const hit = blockIndex.find((b) => b.anchor === anchor);
    if (hit) jumpToAnchor(hit.anchor);
  }, [blockIndex]);

  const calculateStats = (nodes: OutlineNodeType[]) => {
    let total = 0;
    let required = 0;
    let hasTemplate = 0;
    let maxLevel = 0;
    traverseNodes(nodes, (node) => {
      total += 1;
      if (node.required) required += 1;
      if (node.has_template) hasTemplate += 1;
      maxLevel = Math.max(maxLevel, node.level);
    });
    setStats({ total, required, hasTemplate, maxLevel });
  };

  useEffect(() => {
    calculateStats(state.outline);
  }, [state.outline]);

  const selectedNode = useMemo(() => {
    if (!state.selectedUid) return null;
    let found: OutlineNodeType | null = null;
    traverseNodes(state.outline, (node) => {
      if (node.uid === state.selectedUid) found = node;
    });
    return found;
  }, [state.outline, state.selectedUid]);

  const handleDownload = async () => {
    if (!projectId) return;
    if (workflowStage === 'outline_review') {
      setWarnings((prev) => [...prev, '请先确认目录并匹配素材，再生成 Word。']);
      return;
    }
    if (state.isDirty) {
      setWarnings((prev) => [...prev, '目录有未保存修改，请先确认目录并重新匹配素材。']);
      return;
    }
    setRenderLoading(true);
    try {
      const res = await tenderAPI.renderBlankBid(projectId);
      setHasRendered(true);
      localStorage.setItem(`tender-rendered:${projectId}`, '1');
      downloadFromUrl(res.download_url);
      window.setTimeout(() => {
        navigate(`/workbench/${projectId}`);
      }, 100);
    } finally {
      setRenderLoading(false);
    }
  };

  const handleRemoveMaterial = async (nodeId: string, materialIndex: number) => {
    const nextAssignments = materialAssignments.map((item) =>
      String(item.node_id) !== String(nodeId)
        ? item
        : { ...item, materials: item.materials.filter((_, idx) => idx !== materialIndex) },
    );
    setMaterialAssignments(nextAssignments);
    if (!projectId) return;
    try {
      await api.put(`/projects/${projectId}/material-assignments`, {
        material_assignments: nextAssignments,
      });
    } catch (err) {
      console.error('保存素材分配失败', err);
    }
  };
  const handleRemapMaterials = async () => {
    if (!projectId || confirmLoading) return;
    const enterWorkbenchAfterRemap = workflowStage === 'outline_review';
    setConfirmLoading(true);
    setConfirmMessage('正在保存目录');
    try {
      await api.put(`/projects/${projectId}/outline`, { outline: removeUidsFromNodes(state.outline) });
      dispatch({ type: 'SAVE_SUCCESS' });
      setConfirmMessage('正在启动素材匹配');
      await api.post(`/projects/${projectId}/remap-materials`);

      while (true) {
        const statusRes = await api.get<{
          status: string;
          message: string;
          error?: string;
          current_node?: string;
        }>(`/projects/${projectId}/status`);
        const taskStatus = statusRes.data;
        setConfirmMessage(taskStatus.message || '正在处理');
        if (taskStatus.current_node === 'remap_failed') {
          throw new Error(taskStatus.error || taskStatus.message || '素材匹配失败');
        }
        if (taskStatus.status === 'done' && taskStatus.current_node === 'done') break;
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }

      await fetchOutline();
      if (enterWorkbenchAfterRemap) {
        navigate(`/workbench/${projectId}`);
      }
    } catch (err: any) {
      console.error('重跑素材映射失败', err);
      setWarnings((prev) => [...prev, err?.response?.data?.detail || err?.message || '素材匹配失败，请重试。']);
    } finally {
      setConfirmLoading(false);
      setConfirmMessage('');
    }
  };

  const handleRebuildOutlineFromText = async () => {
    const text = outlinePasteText.trim();
    if (!projectId || !text || outlinePasteLoading) return;
    setOutlinePasteLoading(true);
    setOutlinePasteError('');
    try {
      const res = await api.post<{
        ok: boolean;
        outline: RawOutlineNode[];
        notes?: string[];
        remap_error?: string;
      }>(`/projects/${projectId}/outline/from-text`, {
        text,
        remap: false,
      });
      const outlineWithUids = addUidsToNodes(res.data.outline || []);
      dispatch({ type: 'LOAD', payload: outlineWithUids });
      calculateStats(outlineWithUids);
      setOutlinePasteDialogOpen(false);
      setOutlinePasteText('');
      await fetchOutline();
      setWorkflowStage('outline_review');
    } catch (err: any) {
      console.error('粘贴目录重建失败', err);
      setOutlinePasteError(err?.response?.data?.detail || '目录解析失败，请检查粘贴内容后重试。');
    } finally {
      setOutlinePasteLoading(false);
    }
  };

  const handleAskSource = async () => {
    const question = sourceQuestion.trim();
    if (!projectId || !question || sourceAskLoading) return;
    const messageId = `${Date.now()}`;
    setSourceAskLoading(true);
    setSourceAskError('');
    setSourceQuestion('');
    setSourceAskMessages((prev) => [...prev, { id: messageId, question }]);
    try {
      const res = await api.post<SourceAskResponse>(`/projects/${projectId}/source-ask`, {
        question,
        top_k: 14,
      });
      setSourceAskMessages((prev) => prev.map((item) => (item.id === messageId ? { ...item, response: res.data } : item)));
      const firstPage = res.data.citations?.find((item) => item.preview_page_no || item.page_no);
      if (firstPage) setSourcePreviewPage(firstPage.preview_page_no || firstPage.page_no || 1);
    } catch (err) {
      console.error('原文问答失败', err);
      setSourceAskMessages((prev) => prev.filter((item) => item.id !== messageId));
      setSourceQuestion(question);
      setSourceAskError('原文问答失败，请稍后重试或直接查看原文。');
    } finally {
      setSourceAskLoading(false);
    }
  };

  const jumpToSourceCitation = async (citation: SourceAskCitation) => {
    setSourceAskError('');
    const directPage = citation.preview_page_no || citation.page_no;
    if (directPage) {
      setSourcePreviewPage(directPage);
      return;
    }

    const anchor = String(citation.anchor || '').trim();
    if (anchor) {
      const cached = anchorLocations[anchor] || blockLocationMap[anchor];
      const cachedPage = cached?.preview_page_no || cached?.page_no;
      if (cachedPage) {
        setSourcePreviewPage(cachedPage);
        return;
      }

      const incoming = await requestAnchorLocations([anchor]);
      const resolved = incoming[anchor] || anchorLocations[anchor] || blockLocationMap[anchor];
      const resolvedPage = resolved?.preview_page_no || resolved?.page_no;
      if (resolvedPage) {
        setSourcePreviewPage(resolvedPage);
        return;
      }
    }

    setSourceAskError('这条引用没有可定位的原文页码，可能来自系统整理后的目录摘要。');
  };
  const onRemoveMaterialSafe = (nodeId: string, materialIndex: number) => {
    if (!nodeId || materialIndex < 0) return;
    handleRemoveMaterial(nodeId, materialIndex);
    setSelectedMaterialIndex((prev) => (prev > 0 ? prev - 1 : 0));
  };

  const selectedNodeSafe = selectedNode as OutlineNodeType | null;
  const selectedNodeMaterials = useMemo(() => {
    if (!selectedNodeSafe) return [];
    const exact = materialAssignments.find((item) => String(item.node_id) === String(selectedNodeSafe.id));
    if (exact?.materials?.length) return exact.materials;

    const children = selectedNodeSafe.children || [];
    if (!children.length) return [];
    const childIds: string[] = [];
    const walk = (nodes: OutlineNodeType[]) => {
      nodes.forEach((n) => {
        childIds.push(String(n.id));
        if (n.children?.length) walk(n.children as OutlineNodeType[]);
      });
    };
    walk(children as OutlineNodeType[]);

    const merged = materialAssignments
      .filter((item) => childIds.includes(String(item.node_id)))
      .flatMap((item) => item.materials || []);

    return merged;
  }, [selectedNodeSafe, materialAssignments]);
  const selectedRetrievalSummary = useMemo(() => {
    if (!selectedNodeSafe) return null;
    const nodes = retrievalSummary.nodes || [];
    const exact = nodes.find((item) => String(item.node_id) === String(selectedNodeSafe.id));
    if (exact) return exact;

    const children = selectedNodeSafe.children || [];
    if (!children.length) return null;
    const childIds: string[] = [];
    const walk = (items: OutlineNodeType[]) => {
      items.forEach((n) => {
        childIds.push(String(n.id));
        if (n.children?.length) walk(n.children as OutlineNodeType[]);
      });
    };
    walk(children as OutlineNodeType[]);
    const childSummaries = nodes.filter((item) => childIds.includes(String(item.node_id)));
    if (!childSummaries.length) return null;
    const topHits = childSummaries.flatMap((item) => item.top_hits || []).slice(0, 8);
    return {
      node_id: String(selectedNodeSafe.id),
      node_name: selectedNodeSafe.name,
      has_assignment: childSummaries.some((item) => item.has_assignment),
      material_count: childSummaries.reduce((sum, item) => sum + (item.material_count || 0), 0),
      material_fact_count: childSummaries.reduce((sum, item) => sum + (item.material_fact_count || 0), 0),
      confidence: Math.max(...childSummaries.map((item) => item.confidence || 0)),
      retrieval_method: 'children_aggregated',
      top_hits: topHits,
    } satisfies RetrievalNodeSummary;
  }, [selectedNodeSafe, retrievalSummary.nodes]);
  const selectedMaterial = selectedNodeMaterials[selectedMaterialIndex] || null;
  useEffect(() => {
    if (selectedMaterialIndex >= selectedNodeMaterials.length) setSelectedMaterialIndex(0);
  }, [selectedMaterialIndex, selectedNodeMaterials.length]);
  const jumpToAnchor = (anchor: string) => {
    const location = anchorLocations[anchor] || blockLocationMap[anchor];
    const previewPage = typeof location?.preview_page_no === 'number' ? location.preview_page_no : null;
    if (previewPage) {
      setSourcePreviewPage(previewPage);
    }
    const el = anchorRefs.current[anchor];
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const qp = new URLSearchParams(window.location.search);
    qp.set('anchor', anchor);
    window.history.replaceState({}, '', `${window.location.pathname}?${qp.toString()}`);
  };

  const blockLocationMap = useMemo(() => {
    const map: Record<string, ResolvedAnchorLocation> = {};
    blockIndex.forEach((item) => {
      if (!item.anchor) return;
      map[item.anchor] = {
        anchor: item.anchor,
        kind: item.kind,
        text: item.text,
        page_no: item.page_no,
        page_no_end: item.page_no_end,
        preview_page_no: item.preview_page_no,
        preview_page_no_end: item.preview_page_no_end,
      };
    });
    return map;
  }, [blockIndex]);

  const sectionAnchorMap = useMemo(() => {
    const map: Record<string, { start?: string | null; end?: string | null }> = {};
    locatedSections.forEach((section) => {
      const sectionId = String(section.id || '').trim();
      if (!sectionId) return;
      map[sectionId] = { start: section.anchor_start, end: section.anchor_end };
    });
    return map;
  }, [locatedSections]);

  const compactSourceText = (value?: unknown) =>
    String(value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : value)
      .replace(/\s+/g, '')
      .replace(/[，,。；;：:、/／（）()《》【】\[\]"'“”‘’]/g, '');

  const anchorNumber = (anchor?: string | null) => {
    const match = String(anchor || '').match(/^(?:p|b)?(\d+)$/i);
    return match ? Number(match[1]) : null;
  };

  const requirementSearchText = (atom?: RequirementAtom | null) => {
    const value = stringifyRequirementValue(atom?.value);
    return [atom?.quote, value].filter(Boolean).join(' ');
  };

  const searchFragments = (text: string) => {
    const compact = compactSourceText(text);
    const fragments = [compact, compact.slice(0, 80), compact.slice(0, 48), compact.slice(0, 28)].filter((item) => item.length >= 4);
    String(text || '')
      .split(/[\n\r|，,。；;：:、/／\s]+/)
      .map((item) => compactSourceText(item))
      .filter((item) => item.length >= 4)
      .forEach((item) => fragments.push(item.slice(0, 48)));
    return Array.from(new Set(fragments)).sort((a, b) => b.length - a.length);
  };

  const findBestAnchorInSection = (anchor?: RequirementAnchor | null, evidenceText = '') => {
    const sectionId = String(anchor?.section_id || '').trim();
    const sectionAnchor = sectionId ? sectionAnchorMap[sectionId] : undefined;
    const startNo = anchorNumber(sectionAnchor?.start);
    const endNo = anchorNumber(sectionAnchor?.end);
    const fragments = searchFragments(evidenceText);
    if (!sectionAnchor || !fragments.length) return '';

    let bestAnchor = '';
    let bestScore = 0;
    blockIndex.forEach((block) => {
      const currentNo = anchorNumber(block.anchor);
      if (startNo != null && currentNo != null && currentNo < startNo) return;
      if (endNo != null && currentNo != null && currentNo > endNo) return;
      const blockText = compactSourceText(block.text || '');
      if (blockText.length < 4) return;

      let score = 0;
      fragments.forEach((fragment) => {
        if (!fragment) return;
        if (blockText.includes(fragment)) score = Math.max(score, 1000 + Math.min(fragment.length, 200));
        else if (fragment.includes(blockText) && blockText.length >= 8) score = Math.max(score, 600 + Math.min(blockText.length, 120));
      });
      if (score > bestScore) {
        bestScore = score;
        bestAnchor = block.anchor;
      }
    });
    return bestScore >= 604 ? bestAnchor : '';
  };

  const collectAnchorIds = (anchor?: RequirementAnchor | null, evidenceText = '') => {
    const seen = new Set<string>();
    const ordered: string[] = [];
    const push = (value?: string | null) => {
      const key = String(value || '').trim();
      if (!key || seen.has(key)) return;
      seen.add(key);
      ordered.push(key);
    };
    (anchor?.anchor_blocks || []).forEach((block) => push(block.anchor));
    if (!ordered.length) push(findBestAnchorInSection(anchor, evidenceText));
    if (!ordered.length) push(anchor?.anchor_start);
    if (!ordered.length) push(anchor?.anchor_end);
    if (!ordered.length && anchor?.section_id) {
      const sectionAnchor = sectionAnchorMap[String(anchor.section_id).trim()];
      push(sectionAnchor?.start);
      if (!ordered.length) push(sectionAnchor?.end);
    }
    return ordered;
  };

  const formatAnchorPages = (atom?: RequirementAtom | null) => {
    const pages = new Set<number>();
    collectAnchorIds(atom?.anchor, requirementSearchText(atom)).forEach((anchorId) => {
      const loc = anchorLocations[anchorId] || blockLocationMap[anchorId];
      const start = typeof loc?.preview_page_no === 'number' ? loc.preview_page_no : (typeof loc?.page_no === 'number' ? loc.page_no : null);
      if (start == null) return;
      pages.add(start);
    });
    return Array.from(pages).sort((a, b) => a - b);
  };

  const formatPageLabel = (atom?: RequirementAtom | null) => {
    const pages = formatAnchorPages(atom);
    if (!pages.length) return '';
    return `第${pages.join(',')}页`;
  };

  const firstResolvedPage = (
    anchor?: RequirementAnchor | null,
    extraLocations?: Record<string, ResolvedAnchorLocation>,
    evidenceText = '',
  ) => {
    const pages = new Set<number>();
    collectAnchorIds(anchor, evidenceText).forEach((anchorId) => {
      const loc = extraLocations?.[anchorId] || anchorLocations[anchorId] || blockLocationMap[anchorId];
      const start = typeof loc?.preview_page_no === 'number' ? loc.preview_page_no : null;
      const end = typeof loc?.preview_page_no_end === 'number' ? loc.preview_page_no_end : start;
      if (start == null) return;
      if (end != null && end >= start && end - start <= 10) {
        for (let page = start; page <= end; page += 1) pages.add(page);
        return;
      }
      pages.add(start);
    });
    const ordered = Array.from(pages).sort((a, b) => a - b);
    return ordered.length ? ordered[0] : null;
  };

  const mergeResolvedLocations = useCallback((incoming: Record<string, ResolvedAnchorLocation>) => {
    setAnchorLocations((prev) => {
      const changed = Object.entries(incoming).some(([anchor, location]) => {
        const current = prev[anchor];
        return (
          current?.page_no !== location?.page_no ||
          current?.page_no_end !== location?.page_no_end ||
          current?.preview_page_no !== location?.preview_page_no ||
          current?.preview_page_no_end !== location?.preview_page_no_end ||
          current?.text !== location?.text ||
          current?.kind !== location?.kind
        );
      });
      return changed ? { ...prev, ...incoming } : prev;
    });
  }, []);

  const requestAnchorLocations = useCallback(
    async (anchors: string[]) => {
      if (!projectId || !anchors.length) return {} as Record<string, ResolvedAnchorLocation>;
      const uniqueAnchors = Array.from(new Set(anchors.map((anchor) => String(anchor || '').trim()).filter(Boolean)));
      if (!uniqueAnchors.length) return {} as Record<string, ResolvedAnchorLocation>;
      uniqueAnchors.forEach((anchor) => sourceLocateRequestedRef.current.add(anchor));
      try {
        const res = await api.post<{ preview_url?: string; locations?: Record<string, ResolvedAnchorLocation> }>(
          `/projects/${projectId}/source-locate`,
          { anchors: uniqueAnchors },
        );
        if (res.data.preview_url) setSourcePreviewUrl(apiUrl(res.data.preview_url));
        const incoming = res.data.locations || {};
        mergeResolvedLocations(incoming);
        return incoming;
      } catch (err) {
        uniqueAnchors.forEach((anchor) => sourceLocateRequestedRef.current.delete(anchor));
        console.error('source locate failed', err);
        return {} as Record<string, ResolvedAnchorLocation>;
      }
    },
    [projectId, mergeResolvedLocations],
  );

  const previewFrameSrc = useMemo(() => {
    if (!sourcePreviewUrl) return '';
    const page = sourcePreviewPage || 1;
    return `${sourcePreviewUrl}#page=${page}&pagemode=none&navpanes=0&toolbar=1&zoom=55`;
  }, [sourcePreviewUrl, sourcePreviewPage]);

  const locateRequirementSource = async (atom?: RequirementAtom | null) => {
    if (!atom) return;
    const evidenceText = requirementSearchText(atom);
    const collectedAnchors = collectAnchorIds(atom.anchor, evidenceText);
    const firstAnchor = atom.anchor?.anchor_blocks?.[0]?.anchor || collectedAnchors[0] || '';
    if (firstAnchor) {
      jumpToAnchor(firstAnchor);
    }
    let page = firstResolvedPage(atom.anchor, undefined, evidenceText);
    if (!page) {
      const incoming = await requestAnchorLocations(collectAnchorIds(atom.anchor, evidenceText));
      page = firstResolvedPage(atom.anchor, incoming, evidenceText);
    }
    if (page) setSourcePreviewPage(page);
  };

  const stringifyRequirementValue = (value: unknown): string => {
    if (value === null || value === undefined || value === '') return '';
    if (Array.isArray(value)) return value.map((v) => stringifyRequirementValue(v)).filter(Boolean).join('、');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const quotePreview = (quote?: string) => {
    const text = (quote || '').replace(/\s+/g, ' ').trim();
    return text.length > 80 ? `${text.slice(0, 80)}...` : text;
  };

  const requirementDisplayValue = (atom?: RequirementAtom | null) => {
    const value = stringifyRequirementValue(atom?.value);
    return value || quotePreview(atom?.quote) || '未提取到，请查原文';
  };

  const inferScoringType = (item?: ScoringRequirementItem | null) => {
    const haystack = `${item?.score_type || ''} ${item?.category || ''} ${item?.item || ''} ${item?.criteria?.quote || ''} ${item?.criteria?.value || ''}`
      .replace(/\s+/g, '')
      .toLowerCase();
    if (/(综合评审法|最低价法|评审办法|评审步骤|定标方式)/.test(haystack)) return '评审方法';
    if (/(符合性评审|符合性审查|资格性审查)/.test(haystack)) return '符合性评审';
    if (/(价格评分|价格评审|报价评分|报价得分|评审基准价|价格分|报价分)/.test(haystack)) return '价格评分';
    if (/(商务评分|商务评审|业绩|资质|资信|证书|认证|许可证|营业执照|信用|纳税|社保|财务|授权|分签|注册资本|项目负责人|合同经验)/.test(haystack)) {
      return '商务评分';
    }
    if (/(技术评分|技术评审|方案|服务|技术|应急|响应|管理制度|培训|招聘|保障|现场|履约|食品安全|运营)/.test(haystack)) {
      return '技术评分';
    }
    return '评分标准';
  };

  const hasRequirementContent = (atom?: RequirementAtom | null) =>
    Boolean(stringifyRequirementValue(atom?.value) || (atom?.quote || '').trim());

  const renderRequirementRow = (label: string, atom?: RequirementAtom | null) => {
    const pageLabel = formatPageLabel(atom);
    const hasLocator = Boolean(pageLabel || atom?.anchor?.anchor_start || atom?.anchor?.anchor_blocks?.length);
    return (
      <div key={label} className="rounded-md border border-neutral-200 bg-white p-2">
        <div className="min-w-0">
          <div className="text-xs text-neutral-500">{label}</div>
          <div className="mt-1 text-sm font-medium text-neutral-900 break-words">{requirementDisplayValue(atom)}</div>
          <div className="mt-1 text-xs text-neutral-500 break-words">
            {atom?.quote ? `原文: ${quotePreview(atom.quote)}` : '未提取到，请查原文'}
          </div>
          {hasLocator && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700 hover:bg-blue-100"
                onClick={() => locateRequirementSource(atom)}
              >
                <MapPin className="mr-1 h-3 w-3" />
                {pageLabel || '定位原文'}
              </button>
            </div>
          )}
          {atom?.anchor?.section_title && (
            <div className="mt-1 text-[11px] text-neutral-400 break-words">
              来源章节: {atom.anchor.section_id ? `${atom.anchor.section_id} ` : ''}{atom.anchor.section_title}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderRequirementList = (title: string, items?: RequirementAtom[]) => (
    <div className="space-y-2">
      <div className="text-sm font-semibold">{title}</div>
      {(items || []).length > 0 ? (
        (items || []).map((item, idx) => renderRequirementRow(`${title}${idx + 1}`, item))
      ) : (
        <div className="rounded-md border border-neutral-200 bg-white p-2 text-sm text-neutral-500">
          未提取到，请查原文
        </div>
      )}
    </div>
  );

  const renderNamedRequirementRows = (title: string, rows: Array<{ label: string; atom?: RequirementAtom | null }>) => (
    <div className="space-y-2">
      <div className="text-sm font-semibold">{title}</div>
      {rows.length > 0 ? (
        rows.map((row, idx) => renderRequirementRow(`${row.label || title}${idx + 1}`, row.atom))
      ) : (
        <div className="rounded-md border border-neutral-200 bg-white p-2 text-sm text-neutral-500">
          未提取到，请查原文
        </div>
      )}
    </div>
  );

  const renderScoringGroup = (
    title: string,
    rows: Array<{ label: string; atom?: RequirementAtom | null }>,
  ) => (
    <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm font-semibold">{title}</div>
          <Badge variant="outline">{`${rows.length}条`}</Badge>
        </div>
      {rows.length > 0 ? (
        rows.map((row, idx) => (
          <div key={`${title}-${idx}`} className="rounded-md border border-neutral-200 bg-white p-2">
            <div className="text-xs text-neutral-500">{row.label || `${title}${idx + 1}`}</div>
            <div className="mt-1 text-sm font-medium text-neutral-900 break-words">{requirementDisplayValue(row.atom)}</div>
            <div className="mt-1 text-xs text-neutral-500 break-words">
              {row.atom?.quote ? `原文: ${quotePreview(row.atom.quote)}` : '未提取到，请查原文'}
            </div>
            {(formatPageLabel(row.atom) || row.atom?.anchor?.anchor_start || row.atom?.anchor?.anchor_blocks?.length) && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  className="inline-flex items-center rounded-full border border-purple-200 bg-purple-50 px-2 py-0.5 text-[11px] text-purple-700 hover:bg-purple-100"
                  onClick={() => locateRequirementSource(row.atom)}
                >
                  <MapPin className="mr-1 h-3 w-3" />
                  {formatPageLabel(row.atom) || '定位原文'}
                </button>
              </div>
            )}
            {row.atom?.anchor?.section_title && (
              <div className="mt-1 text-[11px] text-neutral-400 break-words">
                来源章节: {row.atom.anchor.section_id ? `${row.atom.anchor.section_id} ` : ''}{row.atom.anchor.section_title}
              </div>
            )}
          </div>
        ))
      ) : (
        <div className="rounded-md border border-neutral-200 bg-white p-2 text-sm text-neutral-500">
          未提取到，请查原文
        </div>
      )}
    </div>
  );

  const renderOverviewSection = (
    title: string,
    description: string,
    count: number | string,
    children: React.ReactNode,
  ) => (
    <Card className="rounded-2xl border-neutral-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-neutral-950">{title}</div>
          <div className="mt-1 text-xs leading-5 text-neutral-500">{description}</div>
        </div>
        <Badge variant="secondary" className="shrink-0 rounded-full px-2.5">{count}</Badge>
      </div>
      <div className="space-y-2">{children}</div>
    </Card>
  );

  const buildScoringRowLabel = (item: ScoringRequirementItem, idx: number) =>
    [
      (item.score_type || inferScoringType(item)) && item.category && (item.score_type || inferScoringType(item)) !== item.category
        ? item.category
        : '',
      item.item,
      item.score != null ? `${item.score}分` : '',
    ]
      .filter(Boolean)
      .join(' / ') || `评分标准${idx + 1}`;

  const qualificationRequirementRows = useMemo(
    () =>
      (tenderRequirements.qualifications || []).map((item, idx) => ({
        label: item.name || `资格要求${idx + 1}`,
        atom: item.requirement,
      })),
    [tenderRequirements.qualifications],
  );

  const technicalRequirementRows = useMemo(
    () =>
      (tenderRequirements.technical_requirements || []).map((item, idx) => ({
        label: item.name || `技术要求${idx + 1}`,
        atom: item.required_value,
      })),
    [tenderRequirements.technical_requirements],
  );

  const scoringOverviewGroups = useMemo(() => {
    const explicitGroups = tenderRequirements.scoring_overview?.groups || [];
    if (explicitGroups.length > 0) {
      return explicitGroups.map((group) => ({
        title: group.score_type || '评分标准',
        totalScore: group.total_score,
        rows: (group.items || []).map((item, idx) => ({
          label: buildScoringRowLabel(item, idx),
          atom: item.criteria,
        })),
      }));
    }

    const groups = new Map<string, { totalScore: number | null; rows: Array<{ label: string; atom?: RequirementAtom | null }> }>();
    (tenderRequirements.scoring || []).forEach((item, idx) => {
      const title = item.score_type || inferScoringType(item) || '评分标准';
      const current = groups.get(title) || { totalScore: 0, rows: [] };
      current.rows.push({
        label: buildScoringRowLabel(item, idx),
        atom: item.criteria,
      });
      if (item.score != null) {
        current.totalScore = (current.totalScore || 0) + item.score;
      }
      groups.set(title, current);
    });
    return Array.from(groups.entries()).map(([title, group]) => ({
      title,
      totalScore: group.totalScore,
      rows: group.rows,
    }));
  }, [tenderRequirements.scoring_overview, tenderRequirements.scoring]);

  const scoringGroupKind = (group: { title: string; rows: Array<{ label: string; atom?: RequirementAtom | null }> }) => {
    const title = group.title || '';
    if (/商务/.test(title)) return 'business';
    if (/技术/.test(title)) return 'technical';
    const haystack = `${title} ${group.rows.map((row) => `${row.label || ''} ${row.atom?.quote || ''} ${stringifyRequirementValue(row.atom?.value)}`).join(' ')}`;
    if (/(商务评分|商务评审|业绩|资质|资信|证书|认证|许可证|营业执照|信用|纳税|社保|财务|授权|注册资本|项目负责人|合同经验)/.test(haystack)) {
      return 'business';
    }
    if (/(技术评分|技术评审|技术方案|服务方案|实施方案|应急|响应方案|管理制度|培训|招聘|保障|现场|履约|运营)/.test(haystack)) {
      return 'technical';
    }
    return 'other';
  };

  const businessScoringGroups = useMemo(
    () => scoringOverviewGroups.filter((group) => scoringGroupKind(group) === 'business'),
    [scoringOverviewGroups],
  );

  const technicalScoringGroups = useMemo(
    () => scoringOverviewGroups.filter((group) => scoringGroupKind(group) === 'technical'),
    [scoringOverviewGroups],
  );

  const otherScoringGroups = useMemo(
    () => scoringOverviewGroups.filter((group) => scoringGroupKind(group) === 'other'),
    [scoringOverviewGroups],
  );

  const scoringRequirementCount = useMemo(
    () => scoringOverviewGroups.reduce((sum, group) => sum + group.rows.length, 0),
    [scoringOverviewGroups],
  );

  const invalidationRequirementRows = useMemo(
    () =>
      (tenderRequirements.invalidation || []).map((item, idx) => ({
        label: `废标项${idx + 1}`,
        atom: {
          value: item.condition,
          quote: item.quote,
          anchor: item.anchor,
          severity: item.severity,
        } satisfies RequirementAtom,
      })),
    [tenderRequirements.invalidation],
  );

  const timelineRequirementRows = useMemo(
    () =>
      (tenderRequirements.timeline || []).map((item, idx) => ({
        label: item.name || item.action || `时间节点${idx + 1}`,
        atom: item.time,
      })),
    [tenderRequirements.timeline],
  );

  const baseInfoSummaryRows = useMemo(
    () =>
      [
        { label: '项目名称', atom: tenderRequirements.base_info?.project_name },
        { label: '项目编号', atom: tenderRequirements.base_info?.tender_no },
        { label: '采购人', atom: tenderRequirements.base_info?.purchaser },
        { label: '招标代理', atom: tenderRequirements.base_info?.agency },
        { label: '投标截止', atom: tenderRequirements.base_info?.submission_deadline },
        { label: '开标时间', atom: tenderRequirements.base_info?.bid_open_time },
        { label: '投标有效期', atom: tenderRequirements.base_info?.bid_validity_period },
        { label: '文档标题', atom: tenderRequirements.base_info?.document_title },
      ].filter((row) => hasRequirementContent(row.atom)),
    [tenderRequirements.base_info],
  );

  const depositSummaryRows = useMemo(
    () =>
      [
        { label: '保证金金额', atom: tenderRequirements.deposit?.amount },
        { label: '保证金缴纳方式', atom: tenderRequirements.deposit?.payment_method },
        { label: '保证金缴纳截止', atom: tenderRequirements.deposit?.payment_deadline },
      ].filter((row) => hasRequirementContent(row.atom)),
    [tenderRequirements.deposit],
  );

  const pricingSummaryRows = useMemo(
    () =>
      [
        { label: '最高限价', atom: tenderRequirements.pricing?.highest_limit },
        { label: '报价方式', atom: tenderRequirements.pricing?.quotation_method },
      ].filter((row) => hasRequirementContent(row.atom)),
    [tenderRequirements.pricing],
  );

  const fileCompositionRows = useMemo(
    () =>
      (tenderRequirements.file_composition || []).map((item, idx) => ({
        label: `${item.order || idx + 1}. ${item.name || `目录项${idx + 1}`}${item.template_ref ? `（${item.template_ref}）` : ''}`,
        atom: item.requirement,
      })),
    [tenderRequirements.file_composition],
  );

  const formatRequirementRows = useMemo(
    () =>
      (tenderRequirements.format_requirements || []).map((item, idx) => ({
        label: item.name || item.template_ref || `格式要求${idx + 1}`,
        atom: item.requirement,
      })),
    [tenderRequirements.format_requirements],
  );

  const materialChecklistRows = useMemo(
    () =>
      (tenderRequirements.material_checklist || []).map((item, idx) => {
        const flags = [
          item.original ? '原件' : '',
          item.copy_sealed ? '复印件盖章' : '',
          item.count ? `${item.count}份` : '',
          item.required === false ? '非必须' : '必须',
        ].filter(Boolean);
        return {
          label: `${item.name || `提交材料${idx + 1}`}${flags.length ? `（${flags.join(' / ')}）` : ''}`,
          atom: item.requirement,
        };
      }),
    [tenderRequirements.material_checklist],
  );

  const contractSummaryRows = useMemo(
    () =>
      [
        { label: '服务/合同期限', atom: tenderRequirements.contract?.service_period },
        { label: '履约保证金', atom: tenderRequirements.contract?.performance_bond },
      ].filter((row) => hasRequirementContent(row.atom)),
    [tenderRequirements.contract],
  );

  const qualificationRequirementCount = qualificationRequirementRows.length;
  const invalidationRequirementCount = invalidationRequirementRows.length;
  const contractRequirementCount =
    contractSummaryRows.length +
    (tenderRequirements.contract?.payment_terms || []).length +
    (tenderRequirements.contract?.acceptance_rules || []).length +
    (tenderRequirements.contract?.penalty_clauses || []).length +
    (tenderRequirements.contract?.other_risks || []).length;

  const allRequirementAnchorIds = useMemo(() => {
    const atoms: Array<RequirementAtom | null | undefined> = [
      tenderRequirements.base_info?.project_name,
      tenderRequirements.base_info?.tender_no,
      tenderRequirements.base_info?.purchaser,
      tenderRequirements.base_info?.agency,
      tenderRequirements.base_info?.submission_deadline,
      tenderRequirements.base_info?.bid_open_time,
      tenderRequirements.base_info?.bid_validity_period,
      tenderRequirements.base_info?.document_title,
      tenderRequirements.deposit?.required,
      tenderRequirements.deposit?.amount,
      tenderRequirements.deposit?.currency,
      tenderRequirements.deposit?.payment_method,
      tenderRequirements.deposit?.payment_deadline,
      tenderRequirements.pricing?.highest_limit,
      tenderRequirements.pricing?.quotation_method,
      ...(tenderRequirements.deposit?.refund_conditions || []),
      ...(tenderRequirements.deposit?.forfeiture_conditions || []),
      ...(tenderRequirements.pricing?.price_components || []),
      ...(tenderRequirements.pricing?.tax_rules || []),
      ...(tenderRequirements.pricing?.abnormal_price_rules || []),
      ...fileCompositionRows.map((row) => row.atom),
      ...formatRequirementRows.map((row) => row.atom),
      ...materialChecklistRows.map((row) => row.atom),
      ...qualificationRequirementRows.map((row) => row.atom),
      ...technicalRequirementRows.map((row) => row.atom),
      ...invalidationRequirementRows.map((row) => row.atom),
      ...timelineRequirementRows.map((row) => row.atom),
      ...baseInfoSummaryRows.map((row) => row.atom),
      ...depositSummaryRows.map((row) => row.atom),
      ...pricingSummaryRows.map((row) => row.atom),
      ...scoringOverviewGroups.flatMap((group) => group.rows.map((row) => row.atom)),
      ...contractSummaryRows.map((row) => row.atom),
      ...(tenderRequirements.contract?.payment_terms || []),
      ...(tenderRequirements.contract?.acceptance_rules || []),
      ...(tenderRequirements.contract?.penalty_clauses || []),
      ...(tenderRequirements.contract?.other_risks || []),
    ];
    const anchors = new Set<string>();
    atoms.forEach((atom) => {
      collectAnchorIds(atom?.anchor, requirementSearchText(atom)).forEach((anchor) => anchors.add(anchor));
    });
    return Array.from(anchors);
  }, [
    tenderRequirements.base_info,
    tenderRequirements.deposit,
    tenderRequirements.pricing,
    tenderRequirements.contract,
    fileCompositionRows,
    formatRequirementRows,
    materialChecklistRows,
    qualificationRequirementRows,
    technicalRequirementRows,
    invalidationRequirementRows,
    timelineRequirementRows,
    baseInfoSummaryRows,
    depositSummaryRows,
    pricingSummaryRows,
    scoringOverviewGroups,
    contractSummaryRows,
    blockIndex,
    sectionAnchorMap,
  ]);

  useEffect(() => {
    if (!projectId || !sourcePreviewUrl || !allRequirementAnchorIds.length) return;
    const missing = allRequirementAnchorIds.filter((anchor) => {
      const existing = anchorLocations[anchor] || blockLocationMap[anchor];
      return typeof existing?.preview_page_no !== 'number' && !sourceLocateRequestedRef.current.has(anchor);
    });
    if (!missing.length) return;
    let cancelled = false;
    requestAnchorLocations(missing)
      .then(() => {
        if (cancelled) return;
      })
      .catch(() => {
        // Keep UI usable even if preview/page locate is unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, sourcePreviewUrl, allRequirementAnchorIds, anchorLocations, blockLocationMap, requestAnchorLocations]);

  const formatConfidence = (value?: number) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '-';
    return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
  };

  const hitSourceLabel = (source?: string) => {
    if (source === 'certificate' || source === 'certificate_category') return '证书';
    if (source === 'tech_section' || source === 'tech_section_candidate') return '技术母版';
    if (source === 'tender_template') return '招标范本';
    if (source === 'manual') return '人工补充';
    return source || '素材';
  };

  const findUidByNodeId = (nodeId: string): string | null => {
    let found: string | null = null;
    traverseNodes(state.outline, (node) => {
      if (String(node.id) === String(nodeId)) found = node.uid;
    });
    return found;
  };

  const jumpToNode = (nodeId: string) => {
    const uid = findUidByNodeId(nodeId);
    if (!uid) return;
    dispatch({ type: 'SELECT', uid });
  };

  useEffect(() => {
    if (loading || !state.outline.length) return;
    const qp = new URLSearchParams(window.location.search);
    const nodeId = qp.get('node');
    if (!nodeId) return;
    jumpToNode(nodeId);
  }, [loading, state.outline.length]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-1/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[calc(100vh-230px)] w-full" />
      </div>
    );
  }

  const isOutlineReview = workflowStage === 'outline_review';

  return (
    <div className="h-full min-h-0 flex flex-col gap-1">
      <Card className="rounded-2xl border-neutral-200 bg-white/95 px-3 py-2 shadow-sm">
        <div className="flex flex-col gap-2 2xl:flex-row 2xl:items-start 2xl:justify-between">
          <div className="min-w-0 space-y-1">
            <div>
              <h1 className="truncate text-lg font-semibold leading-6 text-neutral-950">{titleInfo?.title || '投标文件工作台'}</h1>
              <p className="mt-0.5 truncate text-sm text-neutral-500">{titleInfo?.project_name || '-'}</p>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-neutral-600">
              <div className="flex items-center whitespace-nowrap"><Building className="mr-1 h-3.5 w-3.5" />采购方：{titleInfo?.purchaser || '-'}</div>
              <div className="flex items-center whitespace-nowrap"><User className="mr-1 h-3.5 w-3.5" />投标方：示例科技服务有限公司</div>
              <div className="flex items-center whitespace-nowrap"><FileText className="mr-1 h-3.5 w-3.5" />章节：{stats.total}</div>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-start justify-end gap-2 pt-0 sm:items-start">
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <Button variant="secondary" size="sm" onClick={() => dispatch({ type: 'ADD_CHILD', parentUid: null })}><Plus className="mr-1 h-4 w-4" />添加章节</Button>
              <Button variant="secondary" size="sm" onClick={() => dispatch({ type: 'UNDO' })} disabled={state.history.length <= 1}><Undo2 className="mr-1 h-4 w-4" />撤销</Button>
              <Button variant="secondary" size="sm" onClick={() => dispatch({ type: 'REDO' })} disabled={state.future.length === 0}><Redo2 className="mr-1 h-4 w-4" />重做</Button>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => navigate(`/workbench/${projectId}`)}
                disabled={isOutlineReview || state.isDirty || confirmLoading}
                title={isOutlineReview ? '请先确认目录并匹配素材' : state.isDirty ? '目录有未保存修改，请先保存并重新匹配素材' : undefined}
              >
                <MessageSquare className="mr-1 h-4 w-4" />{isOutlineReview ? '先确认目录' : '编辑工作台'}
              </Button>
              {isOutlineReview && (
                <Button size="sm" onClick={handleRemapMaterials} disabled={confirmLoading}>
                  {confirmLoading ? <><LoaderCircle className="mr-1 h-4 w-4 animate-spin" />{confirmMessage || '处理中...'}</> : '确认目录并匹配素材'}
                </Button>
              )}
              <div className="min-w-[76px] text-xs text-neutral-500">
                {state.saveStatus === 'saving' && <span className="inline-flex items-center"><Save className="mr-1 h-3 w-3 animate-pulse" />保存中</span>}
                {state.saveStatus === 'saved' && <span className="inline-flex items-center text-green-600"><CheckCircle2 className="mr-1 h-3 w-3" />已保存</span>}
                {state.saveStatus === 'failed' && <span className="inline-flex items-center text-red-600"><AlertCircle className="mr-1 h-3 w-3" />保存失败</span>}
              </div>
              <Button onClick={handleDownload} disabled={renderLoading || isOutlineReview}>
                <Download className="mr-1 h-4 w-4" />
                {isOutlineReview ? '先确认目录' : renderLoading ? '生成中...' : hasRendered ? '重新生成并下载' : '生成并下载'}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {isOutlineReview && (
        <Alert className="border-blue-200 bg-blue-50">
          <AlertCircle className="w-4 h-4 text-blue-700" />
          <AlertDescription className="text-blue-800">
            目录草稿已生成。请先检查左侧目录；如有问题可手动编辑或粘贴目录重建，确认后再匹配素材并生成 Word。
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-1 min-h-0 gap-1.5 overflow-hidden">
        <Card className="w-[280px] xl:w-[292px] overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b"><h3 className="font-medium">目录结构</h3></div>
          <OutlineEditor nodes={state.outline} selectedUid={state.selectedUid} onSelect={(uid) => dispatch({ type: 'SELECT', uid })} dispatch={dispatch} />
        </Card>

        {isOutlineReview && (
          <Card className="flex-1 overflow-hidden rounded-2xl border-dashed border-blue-200 bg-gradient-to-br from-blue-50 via-white to-slate-50 p-4">
            <div className="flex h-full min-h-[360px] items-start justify-center pt-4">
              <div className="w-full max-w-xl rounded-3xl border border-white/80 bg-white/85 p-5 shadow-sm">
                <div className="inline-flex items-center rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                  目录确认阶段
                </div>
                <h2 className="mt-3 text-xl font-semibold tracking-tight text-neutral-950">先把目录定准，再匹配素材</h2>
                <p className="mt-3 text-sm leading-6 text-neutral-600">
                  当前不会展示素材分配，也不会生成 Word。请先检查左侧目录是否和招标文件一致；如果不确定目录在哪里，可以直接问原文。
                </p>
                <div className="mt-4 grid gap-2 sm:grid-cols-3">
                  <div className="rounded-2xl border border-neutral-100 bg-white p-3">
                    <div className="text-sm font-semibold text-neutral-900">1. 核对目录</div>
                    <div className="mt-1 text-xs leading-5 text-neutral-500">左侧可以增删章节、拖动和改名。</div>
                  </div>
                  <div className="rounded-2xl border border-neutral-100 bg-white p-3">
                    <div className="text-sm font-semibold text-neutral-900">2. 问原文</div>
                    <div className="mt-1 text-xs leading-5 text-neutral-500">例如问“响应文件组成在哪一页”。</div>
                  </div>
                  <div className="rounded-2xl border border-neutral-100 bg-white p-3">
                    <div className="text-sm font-semibold text-neutral-900">3. 匹配素材</div>
                    <div className="mt-1 text-xs leading-5 text-neutral-500">确认后再跑知识库和渲染。</div>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button onClick={() => setSourceAskDialogOpen(true)} variant="secondary">
                    <MessageSquare className="mr-1 h-4 w-4" />
                    原文问答
                  </Button>
                  <Button onClick={() => setOutlinePasteDialogOpen(true)} variant="secondary">
                    <FileText className="mr-1 h-4 w-4" />
                    粘贴目录重建
                  </Button>
                  <Button onClick={handleRemapMaterials} disabled={confirmLoading}>
                    {confirmLoading ? <><LoaderCircle className="mr-1 h-4 w-4 animate-spin" />{confirmMessage || '处理中...'}</> : '确认目录并匹配素材'}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
        )}


        {!isOutlineReview && (
        <Card className="flex-1 min-w-0 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-neutral-950">{isOutlineReview ? '目录确认' : '素材分配'}</div>
              <div className="text-xs text-neutral-500">
                {isOutlineReview ? '目录确认前不会匹配素材；请检查左侧目录，必要时手动编辑或粘贴目录重建。' : '选择左侧章节，查看当前章节匹配到的证照、技术母版或招标范本。'}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => setAnalysisDialogOpen(true)}>
                <ListChecks className="mr-1 h-4 w-4" />
                查看投标分析
              </Button>
            </div>
          </div>

          {isOutlineReview ? (
            <div className="p-4 overflow-auto">
              <Card className="border-blue-200 bg-blue-50/70 p-4">
                <div className="text-sm font-semibold text-blue-950">等待确认目录</div>
                <div className="mt-2 text-sm leading-6 text-blue-800">
                  系统已生成目录草稿，但还没有开始匹配素材、RAG 检索或生成章节。请先检查左侧目录，如果不对可以手动调整或粘贴目录重建。
                </div>
                <div className="mt-3 text-sm text-blue-800">
                  确认无误后，点击顶部“确认目录并匹配素材”继续。
                </div>
              </Card>
            </div>
          ) : (
            <div className="p-2 overflow-auto overscroll-contain grid grid-cols-1 xl:grid-cols-2 gap-2">
              <div className="space-y-2 min-w-0">
                <div className="text-sm font-semibold">素材条目</div>
                {!selectedNodeSafe ? (
                  <div className="text-sm text-neutral-500">请先选择一个章节。</div>
                ) : selectedNodeMaterials.length === 0 ? (
                  <div className="space-y-2">
                    <div className="text-sm text-neutral-500">当前章节暂无素材分配。</div>
                  <Button size="sm" variant="secondary" onClick={handleRemapMaterials} disabled={confirmLoading}>
                    {confirmLoading ? <><LoaderCircle className="mr-1 h-4 w-4 animate-spin" />{confirmMessage || '处理中...'}</> : '重跑素材匹配'}
                  </Button>
                  </div>
                ) : (
                  selectedNodeMaterials.map((m, idx) => (
                    <button
                      key={`${m.source}-${idx}`}
                      className={`w-full text-left rounded border p-2 text-sm ${
                        selectedMaterialIndex === idx ? 'border-blue-400 bg-blue-50' : 'border-neutral-200 bg-white'
                      }`}
                      onClick={() => setSelectedMaterialIndex(idx)}
                    >
                      <div className="font-medium">
                        {idx + 1}. {(m as any).name || (m as any).title || hitSourceLabel(m.source)}
                      </div>
                      <div className="text-xs text-neutral-500 mt-1">
                        {(m as any).category || (m as any).chapter_id || (m as any).file_path || m.note || '-'}
                      </div>
                    </button>
                  ))
                )}
              </div>
              <div className="space-y-3 min-w-0">
                <Card className="p-3 border-sky-200 bg-sky-50/60">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-sky-950">检索命中</div>
                      <div className="text-xs text-sky-700 mt-1">
                        用于判断“没素材”发生在匹配、RAG 还是渲染阶段
                      </div>
                    </div>
                    <Badge className="bg-white text-sky-700 border-sky-200">
                      {formatConfidence(selectedRetrievalSummary?.confidence)}
                    </Badge>
                  </div>
                  {!selectedNodeSafe ? (
                    <div className="text-xs text-sky-700 mt-3">请选择左侧章节。</div>
                  ) : !selectedRetrievalSummary ? (
                    <div className="mt-3 flex items-center justify-between gap-2">
                      <div className="text-xs text-sky-700">当前章节暂无检索摘要。</div>
                        <Button size="sm" variant="secondary" onClick={handleRemapMaterials} disabled={confirmLoading}>
                          {confirmLoading ? <><LoaderCircle className="mr-1 h-4 w-4 animate-spin" />{confirmMessage || '处理中...'}</> : '重跑素材匹配'}
                        </Button>
                    </div>
                  ) : (
                    <div className="mt-3 space-y-3">
                      <div className="grid grid-cols-3 gap-2 text-center">
                        <div className="rounded-md bg-white/80 border border-sky-100 p-2">
                          <div className="text-[11px] text-sky-600">分配素材</div>
                          <div className="text-base font-semibold text-sky-950">{selectedRetrievalSummary.material_count || 0}</div>
                        </div>
                        <div className="rounded-md bg-white/80 border border-sky-100 p-2">
                          <div className="text-[11px] text-sky-600">事实素材</div>
                          <div className="text-base font-semibold text-sky-950">{selectedRetrievalSummary.material_fact_count || 0}</div>
                        </div>
                        <div className="rounded-md bg-white/80 border border-sky-100 p-2">
                          <div className="text-[11px] text-sky-600">已分配</div>
                          <div className="text-base font-semibold text-sky-950">{selectedRetrievalSummary.has_assignment ? '是' : '否'}</div>
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        {(selectedRetrievalSummary.top_hits || []).slice(0, 6).map((hit, idx) => (
                          <div key={`${hit.source}-${hit.name}-${idx}`} className="rounded-md border border-sky-100 bg-white px-2 py-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <div className="min-w-0 truncate text-sm font-medium text-sky-950">
                                {hit.name || hit.category || hit.chapter_id || '-'}
                              </div>
                              <Badge variant="outline" className="shrink-0 border-sky-200 text-sky-700">
                                {formatConfidence(hit.confidence)}
                              </Badge>
                            </div>
                            <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-sky-700">
                              <span>{hitSourceLabel(hit.source)}</span>
                              {hit.category && <span>分类: {hit.category}</span>}
                              {hit.chapter_id && <span>章节: {hit.chapter_id}</span>}
                              {hit.reason && <span>来源: {hit.reason}</span>}
                            </div>
                          </div>
                        ))}
                        {!(selectedRetrievalSummary.top_hits || []).length && (
                          <div className="text-xs text-sky-700">没有候选命中，可尝试重跑素材匹配或检查知识库。</div>
                        )}
                      </div>
                    </div>
                  )}
                </Card>

                <Card className="p-3">
                  <div className="text-sm font-medium text-neutral-900">素材详情</div>
                  {!selectedMaterial ? (
                    <div className="text-xs text-neutral-500 mt-2">请选择左侧素材条目。</div>
                  ) : (
                    <div className="mt-2 space-y-2 text-sm">
                      <div><span className="text-neutral-500">类型:</span> {hitSourceLabel((selectedMaterial as any).source)}</div>
                      <div><span className="text-neutral-500">分类:</span> {(selectedMaterial as any).category || '-'}</div>
                      <div><span className="text-neutral-500">素材名称:</span> {(selectedMaterial as any).name || '-'}</div>
                      <div><span className="text-neutral-500">素材ID:</span> {(selectedMaterial as any).id || '-'}</div>
                      <div><span className="text-neutral-500">文件路径:</span> {(selectedMaterial as any).file_path || '-'}</div>
                      <div><span className="text-neutral-500">证书编号:</span> {(selectedMaterial as any).cert_number || '-'}</div>
                      <div><span className="text-neutral-500">有效期至:</span> {(selectedMaterial as any).expire_date || '-'}</div>
                      <div><span className="text-neutral-500">章节ID:</span> {(selectedMaterial as any).chapter_id || '-'}</div>
                      <div><span className="text-neutral-500">数量:</span> {(selectedMaterial as any).max_count || '-'}</div>
                      <div><span className="text-neutral-500">备注:</span> {(selectedMaterial as any).note || '-'}</div>
                      <div className="pt-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => selectedNodeSafe && onRemoveMaterialSafe(selectedNodeSafe.id, selectedMaterialIndex)}
                        >
                          删除该素材
                        </Button>
                      </div>
                    </div>
                  )}
                </Card>
              </div>
            </div>
          )}
        </Card>
        )}
      </div>

      <Dialog open={outlinePasteDialogOpen} onOpenChange={setOutlinePasteDialogOpen}>
        <DialogContent className="max-w-[min(860px,calc(100vw-1rem))] sm:max-w-[min(860px,calc(100vw-1rem))]">
          <DialogHeader>
            <DialogTitle>粘贴目录重建</DialogTitle>
            <DialogDescription>
              当系统识别目录不准时，把招标文件里“投标/响应文件组成、目录表、格式清单”复制到这里。系统会用这段内容覆盖当前目录，确认后再匹配素材。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Textarea
              value={outlinePasteText}
              onChange={(event) => setOutlinePasteText(event.target.value)}
              placeholder={`请粘贴招标文件中的目录原文\n支持一级、多级目录编号，如“一、”“1.”“1.1”`}
              className="min-h-[320px] resize-y font-mono text-sm leading-6"
            />
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
              这个操作会把左侧目录替换为你粘贴内容解析出的目录。解析后仍可在左侧手动增删改，再重新生成 Word。
            </div>
            {outlinePasteError && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {outlinePasteError}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setOutlinePasteDialogOpen(false)} disabled={outlinePasteLoading}>
                取消
              </Button>
              <Button onClick={handleRebuildOutlineFromText} disabled={!outlinePasteText.trim() || outlinePasteLoading}>
                {outlinePasteLoading ? '正在解析目录...' : '重建目录'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {sourceAskDialogOpen && (
        <div className="fixed inset-0 z-[120] flex bg-black/20 backdrop-blur-[1px]" onClick={() => setSourceAskDialogOpen(false)}>
          <div className="ml-auto flex h-full w-full max-w-[1180px] flex-col bg-white shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 border-b bg-white px-5 py-4">
              <div>
                <div className="flex items-center gap-2 text-base font-semibold text-neutral-950">
                  <MessageSquare className="h-4 w-4" />
                  原文问答
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  先检索当前招标文件原文，再让 LLM 基于引用回答；点击引用可在右侧跳到对应页。
                </div>
              </div>
              <Button variant="secondary" size="sm" onClick={() => setSourceAskDialogOpen(false)}>
                关闭
              </Button>
            </div>
            <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(360px,0.88fr)_minmax(560px,1.12fr)]">
              <div className="flex min-h-0 flex-col border-r bg-neutral-50/80">
                <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                  {sourceAskMessages.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-neutral-200 bg-white p-5 text-sm leading-6 text-neutral-500">
                      可以直接问：目录在哪里？响应文件由哪些内容组成？需要哪些资质证明？评分标准里技术分怎么给？
                    </div>
                  ) : (
                    sourceAskMessages.map((message) => (
                      <div key={message.id} className="space-y-2">
                        <div className="ml-auto max-w-[86%] rounded-2xl bg-neutral-950 px-3 py-2 text-sm leading-6 text-white shadow-sm">
                          {message.question}
                        </div>
                        <div className="max-w-[94%] rounded-2xl border border-neutral-200 bg-white px-3 py-2 text-sm leading-6 text-neutral-800 shadow-sm">
                          {message.response ? (
                            <>
                              <div className="whitespace-pre-wrap">{message.response.answer}</div>
                              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-neutral-500">
                                <span>可信度：{message.response.confidence === 'high' ? '高' : message.response.confidence === 'medium' ? '中' : '低'}</span>
                                <span>{message.response.used_llm ? 'LLM 已基于引用整理' : '检索兜底回答'}</span>
                              </div>
                              {message.response.citations?.length > 0 && (
                                <div className="mt-2 space-y-1.5">
                                  {message.response.citations.map((citation) => (
                                    <button
                                      key={`${message.id}-${citation.id}`}
                                      type="button"
                                      onClick={() => jumpToSourceCitation(citation)}
                                      className="block w-full rounded-lg border border-neutral-100 bg-neutral-50 px-2 py-1.5 text-left hover:border-blue-200 hover:bg-blue-50"
                                    >
                                      <div className="flex items-center justify-between gap-2 text-[11px] font-semibold text-neutral-700">
                                        <span>{citation.id} {citation.title || '原文片段'}</span>
                                        {(citation.preview_page_no || citation.page_no) ? (
                                          <span>第 {citation.preview_page_no || citation.page_no} 页</span>
                                        ) : citation.anchor ? (
                                          <span>定位原文</span>
                                        ) : (
                                          <span>无页码</span>
                                        )}
                                      </div>
                                      <div className="mt-1 line-clamp-2 text-[11px] text-neutral-500">{citation.quote}</div>
                                    </button>
                                  ))}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="text-neutral-500">正在检索原文...</div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <div className="border-t bg-white p-3">
                  {sourceAskError && <div className="mb-2 text-xs text-red-600">{sourceAskError}</div>}
                  <div className="flex items-end gap-2 rounded-2xl border border-neutral-200 bg-neutral-50 p-2">
                    <textarea
                      value={sourceQuestion}
                      onChange={(event) => setSourceQuestion(event.target.value)}
                      onKeyDown={(event) => {
                        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') handleAskSource();
                      }}
                      placeholder="问当前招标文件，例如：目录在哪里？响应文件需要提交哪些内容？"
                      className="h-16 flex-1 resize-none bg-transparent px-2 py-1 text-sm text-neutral-800 outline-none"
                    />
                    <Button size="sm" onClick={handleAskSource} disabled={!sourceQuestion.trim() || sourceAskLoading}>
                      {sourceAskLoading ? '检索中...' : '发送'}
                    </Button>
                  </div>
                  <div className="mt-1 text-[11px] text-neutral-400">Ctrl/⌘ + Enter 发送</div>
                </div>
              </div>
              <div className="flex min-h-0 flex-col bg-white">
                <div className="border-b px-4 py-3">
                  <div className="text-sm font-semibold text-neutral-950">原文预览</div>
                  <div className="mt-1 text-xs text-neutral-500">点击回答引用后，这里会跳到对应页码。</div>
                </div>
                <div className="min-h-0 flex-1 p-2">
                  {previewFrameSrc ? (
                    <iframe
                      key={previewFrameSrc}
                      title="source-ask-preview"
                      src={previewFrameSrc}
                      className="h-full min-h-0 w-full rounded-lg border border-neutral-200 bg-white"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-neutral-200 bg-neutral-50 p-6 text-sm text-neutral-500">
                      当前原文文件暂不支持预览，请先确认源文件已成功上传。
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <Dialog open={analysisDialogOpen} onOpenChange={setAnalysisDialogOpen}>
        <DialogContent className="h-[94vh] max-w-[min(1580px,calc(100vw-1rem))] overflow-hidden p-0 sm:max-w-[min(1580px,calc(100vw-1rem))]">
          <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(420px,0.95fr)_minmax(520px,1.05fr)]">
            <div className="flex min-h-0 flex-col border-r bg-neutral-50/70">
              <DialogHeader className="border-b bg-white px-4 py-3">
                <DialogTitle className="text-base font-semibold text-neutral-950">投标分析总览</DialogTitle>
                <DialogDescription>
                  汇总基础信息、资格门槛、评分拉分项、格式要求、废标避坑、提交清单与合同风险。点击“定位原文”可在右侧核对来源。
                </DialogDescription>
              </DialogHeader>
              <div className="border-b bg-white px-3 py-2">
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-1 shadow-sm">
                  <div className="grid grid-cols-2 gap-1 md:grid-cols-3 2xl:grid-cols-6">
                    {[
                      { key: 'base', label: '基础信息', count: baseInfoSummaryRows.length + timelineRequirementRows.length + depositSummaryRows.length },
                      { key: 'qualification', label: '资格门槛', count: qualificationRequirementCount },
                      { key: 'scoring', label: '评分拉分项', count: scoringRequirementCount },
                      { key: 'format', label: '格式要求', count: fileCompositionRows.length + formatRequirementRows.length },
                      { key: 'invalid', label: '废标避坑', count: invalidationRequirementCount },
                      { key: 'submit_contract', label: '提交/合同', count: materialChecklistRows.length + contractRequirementCount },
                    ].map((tab) => (
                      <button
                        key={tab.key}
                        className={`rounded-lg px-2.5 py-1.5 text-left text-xs transition ${
                          analysisTab === tab.key
                            ? 'bg-neutral-950 text-white shadow-sm'
                            : 'bg-white text-neutral-600 hover:bg-neutral-100'
                        }`}
                        onClick={() => setAnalysisTab(tab.key as typeof analysisTab)}
                      >
                        <div className="font-medium">{tab.label}</div>
                        <div className={analysisTab === tab.key ? 'text-white/65' : 'text-neutral-400'}>{tab.count} 项</div>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                  <div className="space-y-3">

                    {analysisTab === 'base' && renderOverviewSection(
                      '1. 基础信息与时间轴',
                      '项目编号、招标人、截止时间、开标时间、保证金等全局把控项。',
                      baseInfoSummaryRows.length + timelineRequirementRows.length + depositSummaryRows.length,
                      <>
                        {renderNamedRequirementRows('核心元数据', baseInfoSummaryRows)}
                        {renderNamedRequirementRows('保证金信息', depositSummaryRows)}
                        {renderNamedRequirementRows('关键时间节点', timelineRequirementRows)}
                      </>,
                    )}

                    {analysisTab === 'qualification' && renderOverviewSection(
                      '2. 资格要求与审查',
                      '企业资质、财务、信用、业绩、人员等资格门槛。',
                      qualificationRequirementCount,
                      renderNamedRequirementRows('资格审查要求', qualificationRequirementRows),
                    )}

                    {analysisTab === 'scoring' && renderOverviewSection(
                      '3. 评审要求与评分标准',
                      '价格、商务、技术等评分项，帮助识别硬门槛与拉分方向。',
                      scoringRequirementCount,
                      <>
                        {businessScoringGroups.length > 0 && businessScoringGroups.map((group) =>
                          renderScoringGroup(`商务评分：${group.title}（${group.rows.length}条）`, group.rows),
                        )}
                        {technicalScoringGroups.length > 0 && technicalScoringGroups.map((group) =>
                          renderScoringGroup(`技术评分：${group.title}（${group.rows.length}条）`, group.rows),
                        )}
                        {otherScoringGroups.length > 0 && otherScoringGroups.map((group) =>
                          renderScoringGroup(`${group.title}（${group.rows.length}条）`, group.rows),
                        )}
                        {renderRequirementList('价格/报价规则', [
                          tenderRequirements.pricing?.highest_limit,
                          tenderRequirements.pricing?.quotation_method,
                          ...(tenderRequirements.pricing?.price_components || []),
                          ...(tenderRequirements.pricing?.abnormal_price_rules || []),
                        ].filter(Boolean) as RequirementAtom[])}
                      </>,
                    )}

                    {analysisTab === 'format' && renderOverviewSection(
                      '4. 投标文件要求与格式',
                      '投标文件组成、附件格式、表格模板、签字盖章、密封装订等。',
                      fileCompositionRows.length + formatRequirementRows.length,
                      <>
                        {renderNamedRequirementRows('投标文件组成', fileCompositionRows)}
                        {renderNamedRequirementRows('格式/模板/盖章装订要求', formatRequirementRows)}
                      </>,
                    )}

                    {analysisTab === 'invalid' && renderOverviewSection(
                      '5. 无效标与废标项解析',
                      '禁止清单：否决投标、不予受理、废标、无效响应等条款。',
                      invalidationRequirementCount,
                      renderNamedRequirementRows('无效标与废标项解析', invalidationRequirementRows),
                    )}

                    {analysisTab === 'submit_contract' && (
                      <>
                    {renderOverviewSection(
                      '6. 应标提交文件清单',
                      '投标人需要提交的证明材料，并标注原件、复印件盖章、份数等要求。',
                      materialChecklistRows.length,
                      renderNamedRequirementRows('提交材料 Checklist', materialChecklistRows),
                    )}

                    {renderOverviewSection(
                      '7. 招标文件审查：合同与风险',
                      '付款、验收、违约、履约保证金、服务期等商业风险条款。',
                      contractRequirementCount,
                      <>
                        {renderNamedRequirementRows('合同核心条款', contractSummaryRows)}
                        {renderRequirementList('付款方式', tenderRequirements.contract?.payment_terms)}
                        {renderRequirementList('验收规则', tenderRequirements.contract?.acceptance_rules)}
                        {renderRequirementList('违约/赔偿/扣罚', tenderRequirements.contract?.penalty_clauses)}
                        {renderRequirementList('其他合同风险', tenderRequirements.contract?.other_risks)}
                      </>,
                    )}

                      </>
                    )}
                  </div>
              </div>
            </div>
            <div className="flex min-h-0 flex-col bg-white">
              <div className="border-b px-4 py-3">
                <div className="text-sm font-semibold text-neutral-950">原文对照</div>
                <div className="mt-1 text-xs text-neutral-500">点击左侧条目的定位按钮后，这里会跳到对应页码。</div>
              </div>
              <div className="min-h-0 flex-1 p-2">
                {previewFrameSrc ? (
                  <iframe
                    key={previewFrameSrc}
                    title="analysis-source-preview"
                    src={previewFrameSrc}
                    className="h-full min-h-0 w-full rounded-lg border border-neutral-200 bg-white"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-neutral-200 bg-neutral-50 p-6 text-sm text-neutral-500">
                    当前原文件暂不支持预览，请先确认源文件已成功上传。
                  </div>
                )}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {warnings.length > 0 && (
        <Alert className="bg-amber-50 border-amber-200">
          <AlertCircle className="w-4 h-4 text-amber-700" />
          <AlertDescription className="text-amber-800">系统提示: {warnings.slice(0, 3).join('；')}</AlertDescription>
        </Alert>
      )}
    </div>
  );
};

export default OutlineReview;
