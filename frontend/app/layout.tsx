// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import type { Metadata } from 'next';
import Script from 'next/script';
import type { ReactNode } from 'react';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'Dirijor · Private Realm', template: '%s · Dirijor' },
  description: 'Private Agent Network OS — secure agent orchestration',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const enableFigmaCapture =
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_ENABLE_FIGMA_CAPTURE === 'true';

  return (
    <html lang="en" className="dark">
      <body className="min-h-dvh font-sans antialiased">
        {/* Explicit opt-in keeps the default app path private by default. */}
        {enableFigmaCapture ? (
          <Script
            src="https://mcp.figma.com/mcp/html-to-design/capture.js"
            strategy="afterInteractive"
          />
        ) : null}
        {children}
      </body>
    </html>
  );
}
