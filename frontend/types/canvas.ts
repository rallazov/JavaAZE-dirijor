// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import type { Edge, Node } from 'reactflow';
import type { AgentNodeData, AgentStatus } from './agent';
import type { CriticalAction } from './realm';

/** Graph node on the Private Realm canvas (React Flow node + agent payload). */
export type RealmNode = Node<AgentNodeData>;

/** Alias for human-in-the-loop queue items (Epic 1 Story 1.5). */
export type HITLAction = CriticalAction;

export type RealmEdge = Edge;

export type { AgentStatus };
