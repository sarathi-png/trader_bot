interface CategoryScores {
  TREND: number;
  LEVEL: number;
  MOMENTUM: number;
  PRICE_ACTION: number;
  STRENGTH: number;
}

interface ConfluenceMeterProps {
  categories: CategoryScores;
  totalScore: number;
}

export default function ConfluenceMeter({ categories, totalScore }: ConfluenceMeterProps) {
  const categoryLabels: Record<string, string> = {
    TREND: '📈 Trend',
    LEVEL: '📍 Level',
    MOMENTUM: '⚡ Momentum',
    PRICE_ACTION: '🕯️ Price Action',
    STRENGTH: '💪 Strength',
  };

  return (
    <div className="bg-slate-800 rounded-lg p-4">
      <h3 className="text-lg font-bold mb-3">Confluence Meter</h3>
      <div className="space-y-2">
        {Object.entries(categories).map(([key, score]) => (
          <div key={key} className="flex items-center gap-3">
            <span className="text-sm w-32">{categoryLabels[key] || key}</span>
            <div className="flex-1 bg-slate-700 rounded-full h-3">
              <div
                className={`h-3 rounded-full transition-all ${
                  score >= 2 ? 'bg-green-500' : score >= 1 ? 'bg-yellow-500' : 'bg-red-500'
                }`}
                style={{ width: `${(score / 2) * 100}%` }}
              ></div>
            </div>
            <span className="text-xs w-8 text-right">{score}/2</span>
          </div>
        ))}
      </div>
      <div className="mt-4 pt-3 border-t border-slate-700">
        <div className="flex justify-between items-center">
          <span className="font-bold">Total Score</span>
          <span className={`text-2xl font-bold ${totalScore >= 60 ? 'text-green-400' : totalScore >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
            {totalScore}
          </span>
        </div>
        <div className="w-full bg-slate-700 rounded-full h-2 mt-2">
          <div
            className={`h-2 rounded-full transition-all ${
              totalScore >= 60 ? 'bg-green-500' : totalScore >= 40 ? 'bg-yellow-500' : 'bg-red-500'
            }`}
            style={{ width: `${Math.min(100, totalScore)}%` }}
          ></div>
        </div>
      </div>
    </div>
  );
}
