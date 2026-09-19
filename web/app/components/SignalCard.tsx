interface SignalCardProps {
  signal: {
    asset: string;
    direction: string;
    confidence: number;
    strategies: string[];
    duration: string;
    mtf_trend: string;
    payout: number;
    status: string;
  };
}

export default function SignalCard({ signal }: SignalCardProps) {
  const isCall = signal.direction === 'CALL';
  return (
    <div className={`rounded-lg p-4 border ${isCall ? 'border-green-500/30 bg-green-950/20' : 'border-red-500/30 bg-red-950/20'}`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="font-bold text-lg">{signal.asset}</p>
          <p className="text-sm text-gray-400">{signal.duration} | MTF: {signal.mtf_trend}</p>
        </div>
        <div className="text-right">
          <p className={`text-2xl font-bold ${isCall ? 'text-green-500' : 'text-red-500'}`}>
            {signal.direction}
          </p>
          <p className="text-sm">{signal.confidence}% confidence</p>
        </div>
      </div>
      <div className="mt-2 flex gap-1">
        {signal.strategies.map(s => (
          <span key={s} className="bg-slate-700 px-2 py-0.5 rounded text-xs">{s}</span>
        ))}
      </div>
      <div className="mt-2 text-xs text-gray-500">Payout: {signal.payout}% | Status: {signal.status}</div>
    </div>
  );
}
