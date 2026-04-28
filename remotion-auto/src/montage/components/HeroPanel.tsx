import React from 'react';
import { useVideoConfig, useCurrentFrame, interpolate, Easing } from 'remotion';
import type {FeatureRow} from '../utils';
import {clamp, pickFirstText, lineClampStyle} from '../utils';

interface HeroPanelProps {
  theme: any;
  panelGradient: string;
  panelShiftY: number;
  panelOpacity: number;
  heroLines: {primary: string; secondary: string};
  paragraphText: string;
  featureRows: FeatureRow[];
  isFullWidth?: boolean;
  showOpening: boolean;
  activeScene: any;
  openingInTranslate: number;
  openingInOpacity: number;
}

export const HeroPanel: React.FC<HeroPanelProps> = ({
  theme,
  panelGradient,
  panelShiftY,
  panelOpacity,
  heroLines,
  paragraphText,
  featureRows,
  isFullWidth = false,
  showOpening,
  activeScene,
  openingInTranslate,
  openingInOpacity,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const n = (activeScene.blockName || '').toUpperCase();
  const isHook = n.includes('ХУК') || n.includes('HOOK');
  const isContext = n.includes('КОНТЕКСТ') || n.includes('SETUP') || n.includes('CONTEXT');
  const forceSide = isHook || isContext;
  const effectiveFull = !forceSide;

  // Dynamic theme based on block name
  const getDynamicColor = () => {
    if (n.includes('РИСК')) return '#ff4d4d'; // Red/Orange for risks
    if (n.includes('РЕШЕН')) return '#00ff88'; // Green for solutions
    if (n.includes('ИТОГ') || n.includes('ХУК')) return '#ffaa00'; // Amber
    return theme.accent; // Default cyan
  };

  const dynamicAccent = getDynamicColor();
  const pattern = activeScene.layoutPattern || 'CENTER';
  
  const width = effectiveFull ? '94%' : 720;
  const right = effectiveFull ? '3%' : 80;
  const left = effectiveFull ? '3%' : 'auto';
  const top = effectiveFull ? '3%' : 'auto';
  const bottom = effectiveFull ? '3%' : 80;
  const height = effectiveFull ? '94%' : 'auto';
  const borderRadius = 40;

  return (
    <div
      style={{
        position: 'absolute',
        bottom,
        right,
        left,
        top,
        width,
        height,
        backgroundColor: 'rgba(8, 8, 12, 0.96)',
        background: effectiveFull ? `radial-gradient(circle at ${pattern === 'SPLIT' ? '30%' : '50%'} 50%, ${dynamicAccent}18 0%, rgba(8, 8, 12, 0.99) 75%)` : 'rgba(8, 8, 12, 0.95)',
        backdropFilter: 'blur(40px)',
        borderRadius,
        border: `1px solid ${dynamicAccent}44`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: (effectiveFull && pattern === 'CENTER') ? 'center' : 'flex-start',
        padding: effectiveFull ? '100px 120px' : '70px 60px',
        color: 'white',
        boxShadow: `0 80px 160px rgba(0,0,0,0.8), inset 0 0 100px ${dynamicAccent}08`,
        overflow: 'hidden',
        zIndex: 10,
        opacity: panelOpacity,
        transform: `translateY(${panelShiftY}px)`,
      }}
    >
      <div style={{
        display: 'flex',
        flexDirection: (effectiveFull && pattern === 'SPLIT') ? 'row' : 'column',
        alignItems: (effectiveFull && pattern === 'CENTER') ? 'center' : 'flex-start',
        gap: (effectiveFull && pattern === 'SPLIT') ? 100 : 40,
        height: '100%',
        width: '100%'
      }}>
        {/* Left/Top Section: Title & Subtitle */}
        <div style={{
          flex: (effectiveFull && pattern === 'SPLIT') ? '0 0 45%' : 'none',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: (effectiveFull && pattern === 'SPLIT') ? 'center' : 'flex-start',
          textAlign: (effectiveFull && pattern === 'CENTER') ? 'center' : 'left',
          width: (effectiveFull && pattern === 'SPLIT') ? 'auto' : '100%',
        }}>
          <div style={{
            fontFamily: theme.fontMain,
            fontSize: effectiveFull ? 96 : 48,
            fontWeight: 950,
            lineHeight: 1.0,
            marginBottom: 15,
            letterSpacing: '-0.05em',
            // @ts-ignore
            textWrap: 'balance',
          }}>
            {heroLines.primary}
            {heroLines.secondary && (
              <div style={{
                display: 'inline-flex',
                background: `${dynamicAccent}22`,
                color: dynamicAccent, 
                marginTop: effectiveFull ? 30 : 10,
                padding: '10px 24px',
                borderRadius: 12,
                border: `1px solid ${dynamicAccent}44`,
                fontSize: effectiveFull ? 32 : 20,
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: 2,
                boxShadow: `0 10px 30px ${dynamicAccent}11`
              }}>
                {heroLines.secondary}
              </div>
            )}
          </div>
        </div>

        {/* Dynamic Visualizations Area */}
        <div style={{
          flex: 1,
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center'
        }}>
          {effectiveFull && (
            <div style={{ width: '100%' }}>
              {activeScene.chartType === 'DONUT' ? (
                <div style={{ display: 'flex', justifyContent: 'center', gap: 60 }}>
                  {(activeScene.bars || []).slice(0, 3).map((bar: any, i: number) => {
                    const radius = 80;
                    const circumference = 2 * Math.PI * radius;
                    const progress = interpolate(frame - 20 - i * 5, [0, 25], [0, bar.value], {extrapolateRight: 'clamp'});
                    const offset = circumference - (progress * circumference);
                    return (
                      <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
                        <div style={{ position: 'relative', width: 200, height: 200 }}>
                          <svg width="200" height="200" style={{ transform: 'rotate(-90deg)' }}>
                            <circle cx="100" cy="100" r={radius} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="12" />
                            <circle cx="100" cy="100" r={radius} fill="none" stroke={dynamicAccent} strokeWidth="12" 
                                    strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" 
                                    style={{ filter: `drop-shadow(0 0 10px ${dynamicAccent}88)` }} />
                          </svg>
                          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 44, fontWeight: 900 }}>
                            {Math.round(progress * 100)}%
                          </div>
                        </div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: '#aaa', textAlign: 'center', maxWidth: 160 }}>{bar.label}</div>
                      </div>
                    );
                  })}
                </div>
              ) : activeScene.chartType === 'BENTO' ? (
                <div style={{ 
                  display: 'grid', 
                  gridTemplateColumns: 'repeat(4, 1fr)', 
                  gridTemplateRows: 'repeat(2, 200px)', 
                  gap: 20 
                }}>
                  {/* Bento Card 1: Large */}
                  <div style={{ 
                    gridColumn: 'span 2', gridRow: 'span 2', 
                    background: `${dynamicAccent}11`, border: `1px solid ${dynamicAccent}33`, 
                    borderRadius: 30, padding: 40, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end'
                  }}>
                     <div style={{fontSize: 72, fontWeight: 950, color: dynamicAccent}}>{Math.round((activeScene.bars?.[0]?.value || 0) * 100)}%</div>
                     <div style={{fontSize: 28, fontWeight: 700, marginTop: 10}}>{activeScene.bars?.[0]?.label || 'Показатель'}</div>
                     <div style={{fontSize: 18, color: '#aaa', marginTop: 15}}>{activeScene.insight}</div>
                  </div>
                  {/* Bento Card 2 */}
                  <div style={{ 
                    gridColumn: 'span 2', background: 'rgba(255,255,255,0.03)', 
                    border: '1px solid rgba(255,255,255,0.08)', borderRadius: 30, padding: 30,
                    display: 'flex', alignItems: 'center', gap: 20
                  }}>
                     <div style={{fontSize: 48, fontWeight: 900, color: 'white'}}>{Math.round((activeScene.bars?.[1]?.value || 0) * 100)}</div>
                     <div style={{fontSize: 20, color: '#aaa'}}>{activeScene.bars?.[1]?.label}</div>
                  </div>
                  {/* Bento Card 3 & 4 */}
                  {[2, 3].map(idx => (
                    <div key={idx} style={{ 
                      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', 
                      borderRadius: 30, padding: 25, display: 'flex', flexDirection: 'column', justifyContent: 'center'
                    }}>
                       <div style={{fontSize: 32, fontWeight: 900, color: dynamicAccent}}>{Math.round((activeScene.bars?.[idx]?.value || 0) * 100)}%</div>
                       <div style={{fontSize: 14, color: '#aaa', marginTop: 5, textTransform: 'uppercase'}}>{activeScene.bars?.[idx]?.label}</div>
                    </div>
                  ))}
                </div>
              ) : activeScene.chartType === 'FLOW' ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 40px' }}>
                  {(activeScene.steps || []).map((step: string, i: number) => (
                    <React.Fragment key={i}>
                      <div style={{ 
                        width: 280, padding: 30, background: 'rgba(255,255,255,0.03)', 
                        border: `1px solid ${dynamicAccent}33`, borderRadius: 24,
                        position: 'relative',
                        transform: `scale(${interpolate(frame - 20 - i * 8, [0, 15], [0.8, 1], {extrapolateRight: 'clamp'})})`,
                        opacity: interpolate(frame - 20 - i * 8, [0, 15], [0, 1], {extrapolateRight: 'clamp'})
                      }}>
                        <div style={{ position: 'absolute', top: -20, left: 30, background: dynamicAccent, color: 'black', padding: '4px 12px', borderRadius: 10, fontWeight: 900, fontSize: 14 }}>
                          ШАГ {i + 1}
                        </div>
                        <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.3 }}>{step}</div>
                      </div>
                      {i < (activeScene.steps.length - 1) && (
                        <div style={{ flex: 1, height: 2, background: `linear-gradient(90deg, ${dynamicAccent}, transparent)`, opacity: 0.3, margin: '0 20px' }} />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              ) : activeScene.chartType === 'METRIC_CARDS' ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 30 }}>
                  {(activeScene.bars || []).map((bar: any, i: number) => (
                    <div key={i} style={{ 
                      background: 'rgba(255,255,255,0.02)', padding: 40, borderRadius: 32, 
                      border: `1px solid rgba(255,255,255,0.05)`,
                      boxShadow: '0 20px 40px rgba(0,0,0,0.3)'
                    }}>
                      <div style={{ fontSize: 18, color: '#aaa', textTransform: 'uppercase', letterSpacing: 2, marginBottom: 15 }}>{bar.label}</div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                        <div style={{ fontSize: 84, fontWeight: 950, color: dynamicAccent }}>{Math.round(bar.value * 100)}</div>
                        <div style={{ fontSize: 32, color: 'white', opacity: 0.5 }}>%</div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                /* Fallback COMPARISON or BARS */
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 60 }}>
                   <div style={{ display: 'flex', flexDirection: 'column', gap: 30 }}>
                     {(activeScene.bars || []).map((bar: any, i: number) => (
                        <div key={i}>
                          <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 10}}>
                            <span style={{color: '#aaa'}}>{bar.label}</span>
                            <span style={{color: dynamicAccent, fontWeight: 900}}>{Math.round(bar.value * 100)}%</span>
                          </div>
                          <div style={{height: 12, background: 'rgba(255,255,255,0.05)', borderRadius: 6, overflow: 'hidden'}}>
                            <div style={{height: '100%', width: `${bar.value * 100}%`, background: dynamicAccent, boxShadow: `0 0 20px ${dynamicAccent}44`}} />
                          </div>
                        </div>
                     ))}
                   </div>
                   <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                      {(activeScene.steps || []).map((s: string, i: number) => (
                        <div key={i} style={{padding: 20, background: 'rgba(255,255,255,0.02)', borderLeft: `4px solid ${dynamicAccent}`, borderRadius: '0 12px 12px 0'}}>
                          {s}
                        </div>
                      ))}
                   </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
