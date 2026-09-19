import { Metadata } from 'next';

export const metadata: Metadata = { title: 'Chart | Quotex Bot' };

export default function ChartPage() {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Live Chart</h2>
      <div className="bg-slate-800 rounded-lg p-6 h-96">
        <p className="text-gray-400">Chart loaded via WebSocket connection</p>
        <canvas id="live-chart" className="w-full h-full"></canvas>
      </div>
    </div>
  );
}
