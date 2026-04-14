// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import { AlertTriangle, Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import type { CriticalAction } from '@/types/realm';

interface HumanLoopGateProps {
  actions: CriticalAction[];
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

const requestedAtFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
});

function getRequestedAtLabel(requestedAt?: string | null) {
  if (!requestedAt) {
    return 'Queued for review';
  }

  const parsedDate = new Date(requestedAt);

  if (Number.isNaN(parsedDate.getTime())) {
    return 'Queued for review';
  }

  return `Requested ${requestedAtFormatter.format(parsedDate)} UTC`;
}

export function HumanLoopGate({ actions, onApprove, onReject }: HumanLoopGateProps) {
  if (actions.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-white/10 bg-black/20 px-3 py-4 text-center text-xs text-realm-muted">
        No pending approvals. Destructive operations will surface here with safety scores before execution.
      </p>
    );
  }

  return (
    <div className="space-y-3" role="list" aria-label="Critical actions pending your decision">
      {actions.map((a) => (
        <Card key={a.id} className="border-realm-amber/25 bg-realm-amber/5">
          <CardHeader className="pb-2">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 size-4 text-realm-amber" aria-hidden />
              <div>
                <CardTitle className="text-sm text-zinc-100">{a.title}</CardTitle>
                <CardDescription className="font-mono text-[10px] text-realm-muted">
                  {getRequestedAtLabel(a.requestedAt)} · score {Math.round(a.safetyScore * 100)}%
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-zinc-300">{a.detail}</p>
            <Separator />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="primary"
                size="sm"
                className="flex-1"
                onClick={() => onApprove(a.id)}
                aria-label={`Approve ${a.title}`}
              >
                <Check aria-hidden />
                Approve
              </Button>
              <Button
                type="button"
                variant="danger"
                size="sm"
                className="flex-1"
                onClick={() => onReject(a.id)}
                aria-label={`Reject ${a.title}`}
              >
                <X aria-hidden />
                Reject
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
