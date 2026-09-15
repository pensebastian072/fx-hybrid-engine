'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import type { EquityPoint } from '@/lib/fx-types';
import { format } from 'date-fns';

interface EquityChartProps {
  data: EquityPoint[];
}

const REGIME_COLORS: Record<string, string> = {
  TREND: '#22c55e',
  CHOP: '#f59e0b',
  RISK_OFF: '#ef4444'
};

function CustomTooltip({
  active,
  payload,
  label
}: {
  active?: boolean;
  payload?: { value: number; payload: EquityPoint }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className='bg-card border-border rounded border p-2 text-xs shadow'>
      <p className='font-medium'>{label}</p>
      <p>Equity: {(point.equity * 100 - 100).toFixed(2)}%</p>
      <p style={{ color: REGIME_COLORS[point.regime_label] }}>
        Regime: {point.regime_label}
      </p>
    </div>
  );
}

export function EquityChart({ data }: EquityChartProps) {
  const formatted = data.map((d) => ({
    ...d,
    date: format(new Date(d.timestamp), 'MMM d'),
    pct: parseFloat(((d.equity - 1) * 100).toFixed(2))
  }));

  const minPct = Math.min(...formatted.map((d) => d.pct));
  const maxPct = Math.max(...formatted.map((d) => d.pct));

  return (
    <ResponsiveContainer width='100%' height={200}>
      <AreaChart data={formatted} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id='equityGrad' x1='0' y1='0' x2='0' y2='1'>
            <stop offset='5%' stopColor='#6366f1' stopOpacity={0.3} />
            <stop offset='95%' stopColor='#6366f1' stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray='3 3' stroke='#1e293b' />
        <XAxis
          dataKey='date'
          tick={{ fontSize: 11, fill: '#64748b' }}
          interval='preserveStartEnd'
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#64748b' }}
          tickFormatter={(v) => `${v}%`}
          domain={[
            Math.floor(minPct - 0.5),
            Math.ceil(maxPct + 0.5)
          ]}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type='monotone'
          dataKey='pct'
          stroke='#6366f1'
          strokeWidth={2}
          fill='url(#equityGrad)'
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
