import { Metadata } from 'next';

export const metadata: Metadata = { title: 'Performance | Quotex Bot' };

export default function PerformancePage() {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Performance</h2>
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-slate-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm">Win Rate</p>
          <p className="text-3xl font-bold text-success-500" id="win-rate">--</p>
        </div>
        <div className="bg-slate-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm">Total Signals</p>
          <p className="text-3xl font-bold" id="total-signals">--</p>
        </div>
        <div className="bg-slate-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm">Today</p>
          <p className="text-3xl font-bold" id="today-signals">--</p>
        </div>
      </div>
      <div className="bg-slate-800 rounded-lg p-6">
        <h3 className="text-lg font-bold mb-2">Recent Trades</h3>
        <div id="trade-history" className="space-y-2">
          <p className="text-gray-400">Loading...</p>
        </div>
      </div>
    </div>
  );
}
