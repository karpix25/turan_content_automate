import React from 'react';
import type {ScenePlanItem} from '../types';
import type {IconPick} from '../utils';
import {clamp, pickFirstText, lineClampStyle} from '../utils';
import {CueWords} from './CueWords';

interface LeftPanelProps {
  theme: any;
  panelGradient: string;
  panelShiftY: number;
  panelOpacity: number;
  sceneIcon: IconPick;
  activeScene: ScenePlanItem;
  steps: string[];
  leftPanelBars: Array<{label: string; value: number}>;
  cueWords: any[];
  layout: string;
}

export const LeftPanel: React.FC<LeftPanelProps> = ({
  theme,
  panelGradient,
  panelShiftY,
  panelOpacity,
  sceneIcon,
  activeScene,
  steps,
  leftPanelBars,
  cueWords,
  layout,
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        left: 50,
        top: 54,
        bottom: 52,
        width: 500,
        borderRadius: 32,
        background: panelGradient,
        // backdropFilter removed
        border: `1px solid ${theme.accent}44`,
        boxShadow: `0 24px 60px ${theme.insightGlow}, 0 0 0 1px rgba(255,255,255,0.05)`,
        padding: '36px 30px 28px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        transform: `translateY(${panelShiftY}px)`,
        opacity: panelOpacity,
      }}
    >
      <div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div style={{fontSize: 44, lineHeight: 1}}>{sceneIcon.icon}</div>
          <div
            style={{
              color: theme.accent,
              fontFamily: theme.fontAccent,
              fontSize: 32,
              fontWeight: 800,
              textTransform: 'uppercase',
              lineHeight: 1,
              letterSpacing: 1.2,
              textShadow: '0 2px 10px rgba(0,0,0,0.2)',
              ...lineClampStyle(2), // Increased to 2 lines
            }}
          >
            {sceneIcon.label}
          </div>
        </div>

      <div>
        {/* Eyebrow / Category */}
        <div
          style={{
            color: theme.accent,
            fontFamily: theme.fontMain,
            fontWeight: 800,
            fontSize: 20,
            textTransform: 'uppercase',
            letterSpacing: 2,
            marginBottom: 10,
            opacity: 0.9,
          }}
        >
          {activeScene.keyword || 'КЛЮЧЕВОЕ'}
        </div>

        <div
          style={{
            color: theme.textMain,
            fontFamily: theme.fontMain,
            fontSize: 40,
            lineHeight: 1.15,
            fontWeight: 800,
            marginBottom: 20,
            letterSpacing: -0.8,
            textShadow: '0 2px 15px rgba(0,0,0,0.3)',
            ...lineClampStyle(6),
            wordBreak: 'break-word',
          }}
        >
          {pickFirstText(activeScene.insight, steps[0], activeScene.cta)}
        </div>

        {steps[0] || activeScene.cta ? (
          <div
            style={{
              color: theme.textMuted,
              fontFamily: theme.fontMain,
              fontSize: 26,
              lineHeight: 1.4,
              marginBottom: 22,
              opacity: 0.9,
              ...lineClampStyle(3),
              wordBreak: 'break-word',
            }}
          >
            {pickFirstText(steps[0], activeScene.cta, activeScene.insight)}
          </div>
        ) : null}
      </div>
    </div>

    <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        {leftPanelBars.map((bar, index) => (
          <div key={`${bar.label}-${index}`} style={{display: 'flex', alignItems: 'center', gap: 12}}>
            <div
              style={{
                width: 150,
                color: theme.textMuted,
                fontFamily: theme.fontMain,
                fontSize: 21,
                lineHeight: 1.25,
                ...lineClampStyle(3), // Allow more lines for features
                wordBreak: 'break-word',
                overflowWrap: 'anywhere',
              }}
            >
              {bar.label}
            </div>

            <div
              style={{
                flex: 1,
                height: 16,
                borderRadius: 999,
                background: '#ffffff24',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${Math.round(clamp(bar.value) * 100)}%`,
                  height: '100%',
                  borderRadius: 999,
                  background: `linear-gradient(90deg, ${theme.accent}, ${theme.cta})`,
                }}
              />
            </div>

            <div
              style={{
                minWidth: 54,
                textAlign: 'right',
                color: theme.textMain,
                fontFamily: theme.fontMain,
                fontSize: 18,
                fontWeight: 650,
              }}
            >
              {Math.round(clamp(bar.value) * 100)}%
            </div>
          </div>
        ))}
        <CueWords cueWords={cueWords} theme={theme} />
      </div>
    </div>
  );
};
