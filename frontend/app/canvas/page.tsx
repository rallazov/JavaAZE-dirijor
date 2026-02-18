'use client';
// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// Dirijor Network Canvas – Private Agent Realms

import ReactFlow, { Node, Controls, Background } from 'reactflow';
import 'reactflow/dist/style.css';

export default function DirijorCanvas() {
    const initialNodes: Node[] = [
        { id: '1', position: { x: 100, y: 100 }, data: { label: '👤 You' } },
        { id: '2', position: { x: 500, y: 150 }, data: { label: '🦞 Grok Agent' } },
        { id: '3', position: { x: 500, y: 300 }, data: { label: '🛡️ Harper Security' } },
        { id: '4', position: { x: 900, y: 200 }, data: { label: '📝 Lucas Code' } },
    ];

    return (
        <div className="h-screen w-screen bg-zinc-950 text-white">
            <div className="absolute top-4 left-4 z-10 bg-black/80 p-4 rounded-xl">
                <input placeholder="Describe your realm..." className="bg-zinc-900 px-4 py-2 rounded" />
                <button className="ml-2 bg-emerald-500 px-6 py-2 rounded font-bold">SPIN PRIVATE REALM</button>
            </div>
            <ReactFlow nodes={initialNodes} edges={[]} fitView>
                <Controls />
                <Background />
            </ReactFlow>
        </div>
    );
}
