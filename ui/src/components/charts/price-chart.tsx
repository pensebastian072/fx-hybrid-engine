'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  CandlestickSeries,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp
} from 'lightweight-charts';
import type { Candle } from '@/lib/fx-types';

interface PriceChartProps {
  candles: Candle[];
  symbol?: string;
}

function parseCandleTimeToUtcTimestamp(rawTime: string): UTCTimestamp | null {
  const trimmed = rawTime.trim();
  if (!trimmed) {
    return null;
  }

  // Accept both ISO (`2026-03-07T00:00:00Z`) and space-separated
  // (`2026-03-07 00:00:00+00:00`) inputs.
  const normalized = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T');
  const millis = Date.parse(normalized);
  if (Number.isNaN(millis)) {
    return null;
  }
  return Math.floor(millis / 1000) as UTCTimestamp;
}

export function PriceChart({ candles, symbol = 'EURUSD' }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#94a3b8'
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' }
      },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false
      },
      width: containerRef.current.clientWidth,
      height: 340
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444'
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    const resizeObserver = new ResizeObserver((entries) => {
      if (entries[0] && chartRef.current) {
        chartRef.current.applyOptions({ width: entries[0].contentRect.width });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) return;

    if (candles.length === 0) {
      seriesRef.current.setData([]);
      return;
    }

    const hasSymbolSpecificCandles = candles.some((candle) => Boolean(candle.symbol));
    const sourceCandles = hasSymbolSpecificCandles
      ? candles.filter((candle) => candle.symbol === symbol)
      : candles;

    const invalidTimes: string[] = [];
    const parsed: CandlestickData<UTCTimestamp>[] = [];
    for (const candle of sourceCandles) {
      const timestamp = parseCandleTimeToUtcTimestamp(candle.time);
      if (timestamp === null) {
        invalidTimes.push(candle.time);
        continue;
      }
      parsed.push({
        time: timestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close
      });
    }

    if (invalidTimes.length > 0) {
      console.warn(
        `[PriceChart] Dropped ${invalidTimes.length} candle(s) with invalid timestamps`,
        invalidTimes.slice(0, 3)
      );
    }

    const sorted = parsed.sort((a, b) => a.time - b.time);
    const deduped: CandlestickData<UTCTimestamp>[] = [];
    for (const point of sorted) {
      const last = deduped[deduped.length - 1];
      if (last && last.time === point.time) {
        deduped[deduped.length - 1] = point;
      } else {
        deduped.push(point);
      }
    }

    seriesRef.current.setData(deduped);
    chartRef.current?.timeScale().fitContent();
  }, [candles, symbol]);

  return (
    <div className='w-full'>
      <p className='text-muted-foreground mb-2 text-sm font-medium'>
        {symbol} · Daily
      </p>
      <div ref={containerRef} className='w-full' />
    </div>
  );
}
