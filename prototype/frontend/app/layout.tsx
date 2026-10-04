import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'CONSENTTRACE',
  description: 'Evidence-backed privacy investigation workstation',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
