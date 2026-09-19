import { useEffect, useState } from 'react';

interface SignalData {
  id: string;
  asset: string;
  direction: string;
  confidence: number;
  strategies: string[];
  duration: string;
  mtf_trend: string;
  payout: number;
  status: string;
}

export default function Dashboard() {
  const [signal, setSignal] = useState<SignalData | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:${process.env.NEXT_PUBLIC_WS_PORT || '8765'}`);
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'signal') {
          setSignal(data.data);
        }
      } catch {}
    };
    return () => ws.close();
  }, []);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Live Signal Dashboard</h2>
      <div className="flex items-center gap-2 mb-4">
        <span className={`w-3 h-3 rounded-full ${wsConnected ? 'bg-green-500' : 'bg-red-500'}`}></span>
        <span className="text-sm">{wsConnected ? 'Live' : 'Disconnected'}</span>
      </div>
      {signal ? (
        <div className="bg-slate-800 rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-gray-400 text-sm">Asset</p>
              <p className="text-2xl font-bold">{signal.asset}</p>
            </div>
            <div className="text-center">
              <p className="text-gray-400 text-sm">Direction</p>
              <p className={`text-3xl font-bold ${signal.direction === 'CALL' ? 'text-green-500' : 'text-red-500'}`}>
                {signal.direction}
              </p>
            </div>
            <div className="text-center">
              <p className="text-gray-400 text-sm">Confidence</p>
              <p className="text-3xl font-bold text-primary-400">{signal.confidence}%</p>
            </div>
          </div>
          <div className="mt-4 flex gap-2 flex-wrap">
            {signal.strategies.map(s => (
              <span key={s} className="bg-primary-600 px-3 py-1 rounded text-xs">{s}</span>
            ))}
          </div>
          <div className="mt-4 flex gap-4 text-sm text-gray-400">
            <span>MTF: {signal.mtf_trend}</span>
            <span>Duration: {signal.duration}</span>
            <span>Payout: {signal.payout}%</span>
            <span>Status: {signal.status}</span>
          </div>
        </div>
      ) : (
        <div className="bg-slate-800 rounded-lg p-8 text-center">
          <p className="text-gray-400">Waiting for signal...</p>
        </div>
      )}
    </div>
  );
}
