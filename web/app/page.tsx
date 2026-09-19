import { Metadata } from 'next';
import Dashboard from '@/app/components/Dashboard';
import ConfluenceMeter from '@/app/components/ConfluenceMeter';

export const metadata: Metadata = { title: 'Dashboard | Quotex Bot' };

export default function Home() {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Live Signal Dashboard</h2>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <Dashboard />
        </div>
        <div>
          <ConfluenceMeter
            categories={{ TREND: 2, LEVEL: 1, MOMENTUM: 2, PRICE_ACTION: 1, STRENGTH: 2 }}
            totalScore={8}
          />
        </div>
      </div>
      <div className="mt-6">
        <h3 className="text-lg font-bold mb-4">Recent Signals</h3>
        <div id="signal-list" className="space-y-3">
          <p className="text-gray-400">Connecting to WebSocket...</p>
        </div>
      </div>
    </div>
  );
}
