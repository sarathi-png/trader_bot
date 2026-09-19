import { Metadata } from 'next';

export const metadata: Metadata = { title: 'Signals | Quotex Bot' };

export default function SignalsPage() {
  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Signal History</h2>
      <div id="signals-list" className="space-y-3">
        <p className="text-gray-400">Loading signals...</p>
      </div>
    </div>
  );
}
