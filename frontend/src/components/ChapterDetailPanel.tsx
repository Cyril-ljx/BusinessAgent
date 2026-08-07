import React from 'react';
import { FileText } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { OutlineNode, EditorAction } from '@/lib/outline-editor';

type ChapterDetailPanelProps = {
  selectedNode: OutlineNode | null;
  dispatch: React.Dispatch<EditorAction>;
};

export function ChapterDetailPanel({ selectedNode, dispatch }: ChapterDetailPanelProps) {
  if (!selectedNode) {
    return (
      <div className="h-full flex items-center justify-center p-4 text-sm text-neutral-500">
        请选择左侧章节
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4">
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-600" />
            <CardTitle className="text-lg">章节详情</CardTitle>
          </div>
          <CardDescription>仅保留高频可编辑项，减少无效信息占位</CardDescription>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="chapter-id" className="text-neutral-500 text-sm">
              章节编号
            </Label>
            <Input id="chapter-id" value={selectedNode.id} readOnly disabled className="bg-neutral-50" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="chapter-name" className="text-sm">
              章节名称
            </Label>
            <Input
              id="chapter-name"
              value={selectedNode.name}
              onChange={(e) => dispatch({ type: 'RENAME', uid: selectedNode.uid, name: e.target.value || selectedNode.name })}
              placeholder="输入章节名称"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="chapter-description" className="text-sm">
              章节备注
            </Label>
            <Textarea
              id="chapter-description"
              value={selectedNode.description || ''}
              onChange={(e) => dispatch({ type: 'UPDATE_DESCRIPTION', uid: selectedNode.uid, description: e.target.value })}
              placeholder="输入本章节的备注、编写要求或注意事项..."
              rows={4}
              className="resize-none"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
