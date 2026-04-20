// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import { ShieldCheck, ShieldAlert, ShieldOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { AgentStatus } from '@/types/agent';

const statusCopy: Record<AgentStatus, string> = {
  healthy: 'Healthy — verified path',
  degraded: 'Elevated — review traffic',
  critical: 'Containment suggested',
  pending: 'Awaiting verification',
  quarantined: 'Isolated — policy quarantine',
};

export function SafetyBadge({ status, className }: { status: AgentStatus; className?: string }) {
  const Icon =
    status === 'healthy'
      ? ShieldCheck
      : status === 'degraded' || status === 'pending'
        ? ShieldAlert
        : ShieldOff;
  const variant =
    status === 'healthy'
      ? 'safe'
      : status === 'critical' || status === 'quarantined'
        ? 'critical'
        : 'warn';
  return (
    <Badge variant={variant} className={cn('gap-1 font-mono', className)} title={statusCopy[status]}>
      <Icon className="size-3" aria-hidden />
      {status}
    </Badge>
  );
}
