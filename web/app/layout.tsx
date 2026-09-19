import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Quotex Signal Bot — Dashboard',
  description: 'Real-time trading signals with AI-powered confluence analysis',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-900 text-white">
        <header className="bg-primary-700 text-white px-6 py-4 shadow-lg">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <h1 className="text-xl font-bold">📊 Quotex Signal Bot</h1>
            <nav className="flex gap-4 text-sm">
              <a href="/" className="hover:text-primary-200">Dashboard</a>
              <a href="/signals" className="hover:text-primary-200">Signals</a>
              <a href="/chart" className="hover:text-primary-200">Chart</a>
              <a href="/performance" className="hover:text-primary-200">Performance</a>
            </nav>
          </div>
        </header>
        <main className="max-w-7xl mx-auto p-6">{children}</main>
      </body>
    </html>
  );
}
