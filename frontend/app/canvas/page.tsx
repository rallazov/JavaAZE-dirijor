// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import type { Metadata } from 'next';
import { CanvasShell } from '@/components/canvas/CanvasShell';

export const metadata: Metadata = {
  title: 'Private Realm · Command Canvas',
  description:
    'Zero-trust command canvas — orchestrate AWS-backed agent meshes, Harper security, and human-in-the-loop approvals.',
};

export default function CanvasPage() {
  return <CanvasShell />;
}
